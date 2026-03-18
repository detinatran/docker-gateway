#!/usr/bin/env python3
"""
main.py — Docker MCP Gateway Demo Client (Sprint 3 + 4)

Demonstrates:
  1. Connect to Docker MCP Gateway via stdio
  2. Discover available tools
  3. Sequential tool calls: github → jira → fetch
  4. Parallel tool calls: all 3 simultaneously
  5. Error handling: timeout, missing tool, missing secret

Run:
    python3 client/main.py
"""

import asyncio
import sys
import os

# Add parent dir to path so we can import gateway module
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gateway import GatewayClient, log_info, log_ok, log_warn, log_error, Colors


# The 3 MCP servers we'll demo through the gateway
SERVERS = ["github", "atlassian", "fetch"]


# ─────────────────────────────────────────────────────────────────────────────
# Demo scenarios
# ─────────────────────────────────────────────────────────────────────────────

async def demo_list_tools(client: GatewayClient):
    """Step 1: Discover all available tools through the gateway."""
    print()
    print(f"{Colors.CYAN}{'─' * 65}{Colors.NC}")
    print(f"{Colors.CYAN}  Step 1: Discover Tools{Colors.NC}")
    print(f"{Colors.CYAN}{'─' * 65}{Colors.NC}")
    print()

    tools = await client.list_tools()

    # Group by server (tool names are typically prefixed)
    for tool in tools:
        desc = tool['description'][:80] + "..." if len(tool['description']) > 80 else tool['description']
        print(f"  {Colors.BOLD}{tool['name']:<35}{Colors.NC} {Colors.DIM}{desc}{Colors.NC}")

    print()
    log_ok(f"Total: {len(tools)} tools available")


async def demo_sequential_calls(client: GatewayClient):
    """Step 2: Call tools sequentially — observe container spawn for each."""
    print()
    print(f"{Colors.CYAN}{'─' * 65}{Colors.NC}")
    print(f"{Colors.CYAN}  🔗 Step 2: Sequential Tool Calls{Colors.NC}")
    print(f"{Colors.CYAN}{'─' * 65}{Colors.NC}")
    print()
    log_info("Calling 3 tools one by one. Watch Docker Desktop for containers!")
    print()

    # Call 1: GitHub — search repositories
    log_info("1/3: Searching GitHub repos for 'mcp-server'...")
    r1 = await client.call_tool("search_repositories", {
        "query": "mcp-server language:python",
        "page": 1,
        "perPage": 3,
    })
    if r1["success"]:
        _print_result_preview("GitHub search_repositories", r1["result"])
    print()

    # Call 2: Jira — search issues
    log_info("2/3: Searching Jira issues (JQL query)...")
    r2 = await client.call_tool("jira_search", {
        "jql": "project IS NOT EMPTY ORDER BY created DESC",
        "limit": 3,
    })
    if r2["success"]:
        _print_result_preview("Jira jira_search", r2["result"])
    print()

    # Call 3: Fetch — grab a URL
    log_info("3/3: Fetching httpbin JSON endpoint...")
    r3 = await client.call_tool("fetch", {
        "url": "https://httpbin.org/json",
    })
    if r3["success"]:
        _print_result_preview("Fetch httpbin", r3["result"])
    print()


async def demo_parallel_calls(client: GatewayClient):
    """Step 3: Call all 3 tools in parallel — compare total time vs sequential."""
    print()
    print(f"{Colors.CYAN}{'─' * 65}{Colors.NC}")
    print(f"{Colors.CYAN}  Step 3: Parallel Tool Calls{Colors.NC}")
    print(f"{Colors.CYAN}{'─' * 65}{Colors.NC}")
    print()
    log_info("Calling 3 tools simultaneously. Total time ≈ slowest single call.")
    print()

    calls = [
        ("search_repositories", {
            "query": "docker compose",
            "page": 1,
            "perPage": 2,
        }),
        ("jira_get_all_projects", {}),  # Jira: list all projects
        ("fetch", {
            "url": "https://httpbin.org/json",
        }),
    ]

    results = await client.call_tools_parallel(calls)

    for (name, _), result in zip(calls, results):
        status = f"{Colors.GREEN}[Success]{Colors.NC}" if result["success"] else f"{Colors.RED}[Failed]{Colors.NC}"
        latency = f"{result['latency_ms']:.0f}ms"
        print(f"  {status} {name:<25} {latency:>8}")

    print()


async def demo_error_handling(client: GatewayClient):
    """Step 4: Test error scenarios — tool not found, timeout simulation."""
    print()
    print(f"{Colors.CYAN}{'─' * 65}{Colors.NC}")
    print(f"{Colors.CYAN}  Step 4: Error Handling{Colors.NC}")
    print(f"{Colors.CYAN}{'─' * 65}{Colors.NC}")
    print()

    # Test 1: Non-existent tool
    log_info("Testing: call a tool that doesn't exist...")
    r1 = await client.call_tool("nonexistent_tool", {"param": "value"})
    if not r1["success"]:
        log_warn(f"Expected error caught: {r1['error'][:100]}")
    print()

    # Test 2: Tool with very short timeout (to demonstrate timeout handling)
    log_info("Testing: fetch with very short timeout (0.001s)...")
    r2 = await client.call_tool(
        "fetch",
        {"url": "https://httpbin.org/delay/5"},
        timeout=0.001,
    )
    if not r2["success"]:
        log_warn(f"Expected timeout caught: {r2['error'][:100]}")
    print()

    # Test 3: Invalid arguments
    log_info("Testing: call with invalid/missing arguments...")
    r3 = await client.call_tool("fetch", {})
    if not r3["success"]:
        log_warn(f"Expected error caught: {r3['error'][:100]}")
    else:
        log_info("Tool handled missing args gracefully")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _print_result_preview(label: str, result: str, max_lines: int = 8):
    """Print a truncated preview of a tool result."""
    lines = result.split('\n')
    preview = '\n'.join(lines[:max_lines])
    if len(lines) > max_lines:
        preview += f"\n  {Colors.DIM}... ({len(lines) - max_lines} more lines){Colors.NC}"
    print(f"  {Colors.DIM}┌─ {label} ─────────────────────────────{Colors.NC}")
    for line in preview.split('\n'):
        print(f"  {Colors.DIM}│{Colors.NC} {line[:120]}")
    print(f"  {Colors.DIM}└────────────────────────────────────────{Colors.NC}")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

async def main():
    print()
    print(f"{Colors.MAGENTA}{'═' * 65}{Colors.NC}")
    print(f"{Colors.MAGENTA}  Docker MCP Gateway — Interactive Demo{Colors.NC}")
    print(f"{Colors.MAGENTA}{'═' * 65}{Colors.NC}")
    print()
    log_info(f"Servers: {', '.join(SERVERS)}")
    log_info("Each MCP server runs in its own isolated Docker container")
    log_info("The Gateway handles routing, secrets, and lifecycle")
    print()

    async with GatewayClient.connect(servers=SERVERS, memory="512Mb") as client:
        # Step 1: Discover tools
        await demo_list_tools(client)

        # Step 2: Sequential calls
        await demo_sequential_calls(client)

        # Step 3: Parallel calls
        await demo_parallel_calls(client)

        # Step 4: Error handling
        await demo_error_handling(client)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Interrupted. Cleaning up...{Colors.NC}")
        sys.exit(0)
    except Exception as e:
        print(f"\n{Colors.RED}Fatal error: {e}{Colors.NC}", file=sys.stderr)
        sys.exit(1)
