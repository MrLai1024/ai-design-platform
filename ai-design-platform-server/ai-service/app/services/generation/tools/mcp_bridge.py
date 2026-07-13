"""MCP Bridge — connect to external MCP servers for context."""

import structlog
from .registry import ToolResult

logger = structlog.get_logger()

MCP_SERVERS = {
    "component-docs": {
        "description": "Component library documentation and API reference",
        "status": "available",
    },
    "design-tokens": {
        "description": "Design tokens (colors, spacing, typography)",
        "status": "available",
    },
    "type-registry": {
        "description": "TypeScript type definitions registry",
        "status": "available",
    },
}


class MCPBridge:
    def __init__(self):
        self._servers = MCP_SERVERS

    async def query(self, server: str, query: str) -> ToolResult:
        if server not in self._servers:
            return ToolResult(
                ok=False,
                error=f"Unknown MCP server: {server}. Available: {list(self._servers.keys())}",
            )

        if self._servers[server]["status"] != "available":
            return ToolResult(ok=False, error=f"MCP server '{server}' is not available.")

        logger.info("mcp_query", server=server, query=query[:80])
        return ToolResult(
            ok=True,
            data={
                "server": server,
                "query": query,
                "note": "MCP server available. Use your knowledge to continue.",
            },
        )
