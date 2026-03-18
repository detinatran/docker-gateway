"""
gateway.py — MCP Gateway Client Wrapper (Sprint 3 + 4)

Manages the stdio connection to `docker mcp gateway run`.
Provides structured logging, latency tracking, and error handling.
"""

import asyncio
import json
import time
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


# ─────────────────────────────────────────────────────────────────────────────
# Data structures for structured logging (Sprint 4)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ToolCallLog:
    """Structured log entry for each tool call."""
    timestamp: str
    tool_name: str
    latency_ms: float
    success: bool
    error: str | None = None
    result_preview: str | None = None
    container_id: str | None = None

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "tool": self.tool_name,
            "latency_ms": round(self.latency_ms, 2),
            "success": self.success,
            "error": self.error,
            "result_preview": self.result_preview,
            "container_id": self.container_id,
        }


@dataclass
class GatewayStats:
    """Aggregated stats for the session."""
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    total_latency_ms: float = 0.0
    logs: list[ToolCallLog] = field(default_factory=list)

    @property
    def avg_latency_ms(self) -> float:
        return self.total_latency_ms / self.total_calls if self.total_calls > 0 else 0


# ─────────────────────────────────────────────────────────────────────────────
# Console output helpers
# ─────────────────────────────────────────────────────────────────────────────

class Colors:
    GREEN = "\033[0;32m"
    YELLOW = "\033[1;33m"
    BLUE = "\033[0;34m"
    RED = "\033[0;31m"
    CYAN = "\033[0;36m"
    MAGENTA = "\033[0;35m"
    DIM = "\033[2m"
    BOLD = "\033[1m"
    NC = "\033[0m"


def _log(level: str, color: str, msg: str):
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"{Colors.DIM}{ts}{Colors.NC} {color}[{level}]{Colors.NC} {msg}")


def log_info(msg: str):
    _log("INFO", Colors.BLUE, msg)


def log_ok(msg: str):
    _log(" OK ", Colors.GREEN, msg)


def log_warn(msg: str):
    _log("WARN", Colors.YELLOW, msg)


def log_error(msg: str):
    _log("ERR ", Colors.RED, msg)


def log_tool(tool: str, msg: str):
    _log("TOOL", Colors.CYAN, f"{Colors.BOLD}{tool}{Colors.NC} → {msg}")


# ─────────────────────────────────────────────────────────────────────────────
# Gateway Client
# ─────────────────────────────────────────────────────────────────────────────

class GatewayClient:
    """
    Wraps the MCP ClientSession connected to Docker MCP Gateway via stdio.
    
    Usage:
        async with GatewayClient.connect(profile="demo") as client:
            tools = await client.list_tools()
            result = await client.call_tool("github_list_repos", {"owner": "docker"})
    """

    def __init__(self, session: ClientSession, profile: str):
        self._session = session
        self._profile = profile
        self._stats = GatewayStats()
        self._tools_cache: list[dict] | None = None

    @staticmethod
    @asynccontextmanager
    async def connect(
        servers: list[str] | None = None,
        verbose: bool = False,
        memory: str = "512Mb",
    ):
        """
        Connect to the Docker MCP Gateway via stdio transport.
        
        The gateway is started as a subprocess via `docker mcp gateway run`.
        Each MCP server runs in its own isolated Docker container.
        
        Args:
            servers: Specific servers to enable (e.g. ["github", "brave", "fetch"]).
                     If None, uses all currently enabled servers.
            verbose: Enable verbose gateway output.
            memory:  Memory limit per container (default 512Mb).
        """
        args = ["mcp", "gateway", "run", "--memory", memory]

        # If specific servers requested, pass them via --servers flag
        if servers:
            for s in servers:
                args.extend(["--servers", s])

        if verbose:
            args.append("--verbose")

        server_params = StdioServerParameters(
            command="docker",
            args=args,
        )

        label = ", ".join(servers) if servers else "all enabled"
        log_info(f"Connecting to MCP Gateway (servers: {label})...")

        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                # MCP handshake
                await session.initialize()
                log_ok("Connected to MCP Gateway")

                client = GatewayClient(session, label)
                yield client

                # Print session summary on exit
                client._print_summary()

    async def list_tools(self) -> list[dict]:
        """
        Discover all tools available through the gateway.
        Results are cached for the session lifetime.
        """
        if self._tools_cache is not None:
            return self._tools_cache

        log_info("Discovering available tools...")
        start = time.perf_counter()

        result = await self._session.list_tools()
        elapsed = (time.perf_counter() - start) * 1000

        tools = []
        for tool in result.tools:
            tools.append({
                "name": tool.name,
                "description": tool.description or "",
                "input_schema": tool.inputSchema if hasattr(tool, 'inputSchema') else {},
            })

        self._tools_cache = tools
        log_ok(f"Found {len(tools)} tools ({elapsed:.0f}ms)")
        return tools

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> dict:
        """
        Call a tool through the gateway with structured logging.
        
        Returns a dict with keys: success, result, latency_ms, error
        """
        arguments = arguments or {}
        ts = datetime.now(timezone.utc).isoformat()

        log_tool(tool_name, f"calling with {json.dumps(arguments, default=str)[:100]}...")

        start = time.perf_counter()
        try:
            result = await asyncio.wait_for(
                self._session.call_tool(tool_name, arguments),
                timeout=timeout,
            )
            elapsed = (time.perf_counter() - start) * 1000

            # Extract text content from result
            content_parts = []
            for content in result.content:
                if hasattr(content, 'text'):
                    content_parts.append(content.text)
                elif hasattr(content, 'data'):
                    content_parts.append(f"[binary data: {len(content.data)} bytes]")
                else:
                    content_parts.append(str(content))

            result_text = "\n".join(content_parts)
            preview = result_text[:200] + "..." if len(result_text) > 200 else result_text

            # Structured log
            log_entry = ToolCallLog(
                timestamp=ts,
                tool_name=tool_name,
                latency_ms=elapsed,
                success=True,
                result_preview=preview,
            )
            self._record(log_entry)

            log_ok(f"{tool_name} completed in {elapsed:.0f}ms")

            return {
                "success": True,
                "result": result_text,
                "latency_ms": elapsed,
                "error": None,
            }

        except asyncio.TimeoutError:
            elapsed = (time.perf_counter() - start) * 1000
            error_msg = f"Timeout after {timeout}s"

            log_entry = ToolCallLog(
                timestamp=ts,
                tool_name=tool_name,
                latency_ms=elapsed,
                success=False,
                error=error_msg,
            )
            self._record(log_entry)
            log_error(f"{tool_name}: {error_msg}")

            return {
                "success": False,
                "result": None,
                "latency_ms": elapsed,
                "error": error_msg,
            }

        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            error_msg = f"{type(e).__name__}: {e}"

            log_entry = ToolCallLog(
                timestamp=ts,
                tool_name=tool_name,
                latency_ms=elapsed,
                success=False,
                error=error_msg,
            )
            self._record(log_entry)
            log_error(f"{tool_name}: {error_msg}")

            return {
                "success": False,
                "result": None,
                "latency_ms": elapsed,
                "error": error_msg,
            }

    async def call_tools_parallel(
        self,
        calls: list[tuple[str, dict[str, Any]]],
        timeout: float = 30.0,
    ) -> list[dict]:
        """
        Call multiple tools concurrently via asyncio.gather.
        
        Each tuple is (tool_name, arguments).
        Returns list of results in the same order.
        """
        log_info(f"Calling {len(calls)} tools in parallel...")
        start = time.perf_counter()

        tasks = [
            self.call_tool(name, args, timeout=timeout)
            for name, args in calls
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        total_ms = (time.perf_counter() - start) * 1000
        log_ok(f"Parallel batch completed in {total_ms:.0f}ms total")

        # Convert any exceptions to error dicts
        final = []
        for r in results:
            if isinstance(r, Exception):
                final.append({
                    "success": False,
                    "result": None,
                    "latency_ms": 0,
                    "error": str(r),
                })
            else:
                final.append(r)
        return final

    def _record(self, log_entry: ToolCallLog):
        """Record a log entry and update stats."""
        self._stats.logs.append(log_entry)
        self._stats.total_calls += 1
        self._stats.total_latency_ms += log_entry.latency_ms
        if log_entry.success:
            self._stats.successful_calls += 1
        else:
            self._stats.failed_calls += 1

    def _print_summary(self):
        """Print session summary with stats."""
        s = self._stats
        print()
        print(f"{Colors.MAGENTA}{'═' * 65}{Colors.NC}")
        print(f"{Colors.MAGENTA}  📊 Session Summary{Colors.NC}")
        print(f"{Colors.MAGENTA}{'═' * 65}{Colors.NC}")
        print(f"  Profile:          {self._profile}")
        print(f"  Total calls:      {s.total_calls}")
        print(f"  Successful:       {Colors.GREEN}{s.successful_calls}{Colors.NC}")
        print(f"  Failed:           {Colors.RED}{s.failed_calls}{Colors.NC}")
        print(f"  Avg latency:      {s.avg_latency_ms:.0f}ms")
        print(f"  Total latency:    {s.total_latency_ms:.0f}ms")
        print()

        if s.logs:
            print(f"  {'Tool':<30} {'Latency':>10} {'Status':>10}")
            print(f"  {'─' * 30} {'─' * 10} {'─' * 10}")
            for log in s.logs:
                status = f"{Colors.GREEN}✓{Colors.NC}" if log.success else f"{Colors.RED}✗{Colors.NC}"
                print(f"  {log.tool_name:<30} {log.latency_ms:>8.0f}ms {status:>10}")

        print(f"{Colors.MAGENTA}{'═' * 65}{Colors.NC}")
        print()

    def get_stats(self) -> dict:
        """Return stats as a dict (useful for automated testing)."""
        return {
            "total_calls": self._stats.total_calls,
            "successful_calls": self._stats.successful_calls,
            "failed_calls": self._stats.failed_calls,
            "avg_latency_ms": self._stats.avg_latency_ms,
            "logs": [log.to_dict() for log in self._stats.logs],
        }
