"""MCP Bridge — connect to real MCP servers via stdio transport."""

import asyncio
import json
import re
import structlog
from .registry import ToolResult

logger = structlog.get_logger()

MCP_SERVERS = {
    "component-docs": {
        "description": "Component library documentation and API reference",
        "command": "npx",
        "args": ["-y", "@anthropic/mcp-server-tdesign"],
        "enabled": True,
    },
    "design-tokens": {
        "description": "Design tokens (colors, spacing, typography)",
        "command": "node",
        "args": ["./mcp-servers/design-tokens-server.js"],
        "enabled": False,
    },
    "type-registry": {
        "description": "TypeScript type definitions from generated files",
        "enabled": True,
        "internal": True,
    },
}


class MCPBridge:
    """Manages connections to MCP servers."""

    def __init__(self):
        self._servers = MCP_SERVERS
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._type_registry: dict[str, str] = {}

    def set_type_registry(self, files: dict[str, str]) -> None:
        """Update the internal type-registry with generated files."""
        self._type_registry = {}
        for path, content in files.items():
            if path.endswith(".ts") or path.endswith(".vue"):
                self._type_registry[path] = content

    async def query(self, server: str, query: str) -> ToolResult:
        """Query an MCP server. Falls back to stub if server unavailable."""
        if server not in self._servers:
            return ToolResult(
                ok=False,
                error=f"Unknown MCP server: {server}. Available: {list(self._servers.keys())}",
            )

        cfg = self._servers[server]
        if not cfg.get("enabled", True):
            return ToolResult(ok=False, error=f"MCP server '{server}' is not enabled.")

        # Internal type-registry (no external process)
        if cfg.get("internal"):
            return await self._query_type_registry(query)

        # External MCP server via stdio
        try:
            result = await self._query_external_mcp(server, cfg, query)
            return result
        except Exception as e:
            logger.warning("mcp_external_failed", server=server, error=str(e))
            # Fallback: stub response so LLM can continue
            return ToolResult(
                ok=True,
                data={
                    "server": server,
                    "query": query,
                    "note": f"MCP server '{server}' temporarily unavailable ({str(e)[:100]}). Use your knowledge to continue.",
                },
            )

    async def _query_type_registry(self, query: str) -> ToolResult:
        """Search internal type registry."""
        query_lower = query.lower()
        results = []
        for path, content in self._type_registry.items():
            if query_lower in content.lower() or query_lower in path.lower():
                results.append({
                    "file": path,
                    "matches": self._extract_types(content, query),
                })
        return ToolResult(ok=True, data={
            "server": "type-registry",
            "query": query,
            "results": results if results else None,
            "note": "No matching types found" if not results else f"Found in {len(results)} files",
        })

    def _extract_types(self, content: str, query: str) -> list[str]:
        """Extract type/interface definitions matching query."""
        pattern = re.compile(
            r'(?:export\s+)?(?:interface|type)\s+(\w[\w\d]*)\s*(?:extends\s+[^{]+)?\s*\{([^}]+)\}',
            re.MULTILINE | re.DOTALL,
        )
        query_lower = query.lower()
        matches = []
        for m in pattern.finditer(content):
            name = m.group(1)
            body = m.group(2)
            if query_lower in name.lower() or query_lower in body.lower():
                matches.append(f"{name} {{ {body[:200].strip()} }}")
        return matches[:5]

    async def _query_external_mcp(
        self, server: str, cfg: dict, query: str
    ) -> ToolResult:
        """Connect to an external MCP server via stdio and send a query."""
        if server not in self._processes:
            try:
                proc = await asyncio.create_subprocess_exec(
                    cfg["command"],
                    *cfg.get("args", []),
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                self._processes[server] = proc
                logger.info("mcp_process_started", server=server, pid=proc.pid)
            except FileNotFoundError:
                raise RuntimeError(f"MCP command not found: {cfg['command']}")

        proc = self._processes[server]

        request = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "search",
                "arguments": {"query": query},
            },
        }) + "\n"

        try:
            proc.stdin.write(request.encode())
            await proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            del self._processes[server]
            raise RuntimeError(f"MCP process for '{server}' disconnected")

        try:
            raw = await asyncio.wait_for(proc.stdout.readline(), timeout=10)
            response = json.loads(raw.decode())
            return ToolResult(ok=True, data={
                "server": server,
                "query": query,
                "result": response.get("result", response),
            })
        except asyncio.TimeoutError:
            return ToolResult(
                ok=True,
                data={
                    "server": server,
                    "query": query,
                    "note": f"MCP '{server}' query timed out. Use your knowledge.",
                },
            )
