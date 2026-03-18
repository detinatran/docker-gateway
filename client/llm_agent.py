#!/usr/bin/env python3
"""
llm_agent.py — Connect an LLM to the Docker MCP Gateway!

Flow:
1. Ask LLM to pick the necessary MCP servers based on user prompt (if not specified).
2. Start the Gateway with the selected servers.
3. Pass all tools from the Gateway to the LLM.
4. Execute any tools the LLM wants, until it gives a final answer.

Usage:
    export OPENAI_API_KEY=your_key  # Can point to OpenAI, Groq, or any OpenAI-compatible API
    python3 client/llm_agent.py "Find issues in my Jira matching 'login bug' then search github for python MCP clients"
    
    # Or force specific servers:
    python3 client/llm_agent.py --servers atlassian,fetch "Summarize Jira issue PROJ-123"
"""

import asyncio
import os
import sys
import json
import argparse
from typing import List

# Add parent dir to path so we can import gateway module
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gateway import GatewayClient, log_info, log_ok, log_warn, log_error, Colors

try:
    from openai import AsyncOpenAI
except ImportError:
    print(f"{Colors.RED}Missing openai package. Run: pip install openai{Colors.NC}")
    sys.exit(1)

try:
    from dotenv import load_dotenv
    # Load .env file from the project root (one level up from client/)
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
    load_dotenv(env_path)
except ImportError:
    pass # If dotenv is somehow not installed, fallback to system env vars


AVAILABLE_SERVERS = ["github", "atlassian", "fetch"]


async def get_servers_for_prompt(prompt: str, llm_client: AsyncOpenAI, model: str) -> List[str]:
    """Ask the LLM which servers are needed for the task."""
    system_prompt = f"""
You are a routing agent. Available tool servers are:
{json.dumps(AVAILABLE_SERVERS)}

- 'github': repos, issues, PRs, code search, users, etc.
- 'atlassian': Jira issues, sprints, projects, Confluence pages, etc.
- 'fetch': fetch public URL contents (curl/http GET).

Based on the user's prompt, reply ONLY with a JSON array of the server strings you need.
Example: ["github", "atlassian"]
If unsure, return all of them: {json.dumps(AVAILABLE_SERVERS)}
"""
    log_info("Asking LLM to pick required MCP servers...")
    
    response = await llm_client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ],
        response_format={"type": "json_object"} if "gpt" in model else None,
        max_tokens=50,
        temperature=0.0
    )
    
    content_raw = response.choices[0].message.content
    content = content_raw.strip() if content_raw else ""
    
    try:
        # Some models wrap json in markdown
        if content.startswith("```json"):
            content = content[7:-3].strip()
        elif content.startswith("```"):
            content = content[3:-3].strip()
            
        selected = json.loads(content)
        if isinstance(selected, dict) and "servers" in selected:
            selected = selected["servers"]
        
        valid = [s for s in selected if s in AVAILABLE_SERVERS]
        if not valid:
            return AVAILABLE_SERVERS
        return list(set(valid))
    except Exception as e:
        log_warn(f"Failed to parse LLM server selection ({e}). Defaulting to all.")
        return AVAILABLE_SERVERS


async def convert_mcp_to_openai_tools(mcp_tools: list) -> list:
    """Convert MCP tools to OpenAI function calling format."""
    openai_tools = []
    for tool in mcp_tools:
        # OpenAI tool names must match ^[a-zA-Z0-9_-]{1,64}$
        safe_name = tool["name"][:64]
        
        openai_tools.append({
            "type": "function",
            "function": {
                "name": safe_name,
                "description": tool.get("description", "No description")[:1024],
                "parameters": tool.get("inputSchema", {
                    "type": "object",
                    "properties": {}
                })
            }
        })
    return openai_tools


async def run_agent(prompt: str, servers: List[str], llm_client: AsyncOpenAI, model: str):
    """Run the main agent loop with the Gateway."""
    log_info(f"Starting Gateway with servers: {', '.join(servers)}...")
    
    async with GatewayClient.connect(servers=servers) as gateway:
        # 1. Get Tools
        mcp_tools = await gateway.list_tools()
        log_ok(f"Loaded {len(mcp_tools)} tools from Gateway.")
        
        if not mcp_tools:
            log_warn("No tools available. Exiting.")
            return

        openai_tools = await convert_mcp_to_openai_tools(mcp_tools)
        
        # 2. Agent Loop
        messages = [
            {"role": "system", "content": "You are a helpful assistant with access to tools via Docker MCP Gateway. Call tools sequentially or in parallel to fulfill the user's request. Output directly and professionally without conversational filler like 'Sure!' or 'Here is the data'."},
            {"role": "user", "content": prompt}
        ]
        
        print(f"\n{Colors.MAGENTA}Agent started! Model: {model}{Colors.NC}")
        print(f"{Colors.BLUE}User:{Colors.NC} {prompt}\n")
        
        while True:
            response = await llm_client.chat.completions.create(
                model=model,
                messages=messages,
                tools=openai_tools,
                tool_choice="auto",
            )
            
            message = response.choices[0].message
            messages.append(message)  # Add assistant message to history
            
            if message.content:
                print(f"{Colors.GREEN}Response:{Colors.NC}\n{message.content}")
                
            if not message.tool_calls:
                # No more tools to call, we are done
                break
                
            # Execute Tool Calls
            print(f"\n{Colors.CYAN}[LLM requested {len(message.tool_calls)} tool calls]{Colors.NC}")
            
            tool_results = []
            
            # We can run these in parallel, but for simplistic logging we will process them
            for tool_call in message.tool_calls:
                tool_name = tool_call.function.name
                args = json.loads(tool_call.function.arguments)
                
                print(f"  {Colors.YELLOW}→ [{tool_name}]{Colors.NC} with args: {args}")
                
                # Execute via Gateway
                result = await gateway.call_tool(tool_name, args)
                
                if result["success"]:
                    out = result["result"]
                    preview = out[:200] + "..." if len(out) > 200 else out
                    print(f"  {Colors.GREEN}[Success]{Colors.NC} {len(out)} chars returned.")
                    print(f"    {Colors.DIM}{preview.replace(chr(10), ' ')}{Colors.NC}")
                    
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_name,
                        "content": out
                    })
                else:
                    err = result["error"]
                    print(f"  {Colors.RED}[Failed]{Colors.NC} {err}")
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_name,
                        "content": f"Error calling tool: {err}"
                    })
            print() # Spacer 


async def main():
    parser = argparse.ArgumentParser(description="Docker MCP LLM Agent")
    parser.add_argument("prompt", help="The task you want the agent to perform")
    parser.add_argument("--servers", help="Comma-separated list of servers to use (e.g. github,atlassian). If omitted, LLM will pick.")
    parser.add_argument("--model", default=os.getenv("LLM_MODEL", "gemini-2.5-flash"), help="The LLM model to use")
    
    args = parser.parse_args()
    
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        print(f"{Colors.RED}Error: GEMINI_API_KEY or OPENAI_API_KEY environment variable is missing.{Colors.NC}")
        print("Please export a GEMINI_API_KEY (from Google AI Studio) or OPENAI_API_KEY.")
        sys.exit(1)
        
    # If using Gemini key without a custom base_url, point to AI Studio's OpenAI compatible endpoint
    base_url = os.getenv("OPENAI_BASE_URL")
    if os.getenv("GEMINI_API_KEY") and not base_url:
        base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"

    client = AsyncOpenAI(
        api_key=api_key,
        base_url=base_url # allows overriding for OpenRouter/Ollama/etc
    )

    servers = []
    if args.servers:
        servers = [s.strip() for s in args.servers.split(",")]
        log_info(f"User forced servers: {servers}")
    else:
        servers = await get_servers_for_prompt(args.prompt, client, args.model)
        log_ok(f"LLM dynamically selected servers: {servers}")
        
    await run_agent(args.prompt, servers, client, args.model)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Agent interrupted.{Colors.NC}")
    except Exception as e:
        print(f"\n{Colors.RED}Agent Error: {e}{Colors.NC}")
