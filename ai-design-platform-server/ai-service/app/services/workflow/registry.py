"""NodeRegistry — maps node type strings to their Handler instances."""

from __future__ import annotations

from .handlers import NodeHandler


class NodeRegistry:
    """A singleton-style registry that maps node type strings to NodeHandler instances.

    Usage::

        NodeRegistry.register(LLMHandler())
        handler = NodeRegistry.lookup("llm")
        types = NodeRegistry.list_types()
        NodeRegistry.reset()
    """

    _handlers: dict[str, NodeHandler] = {}

    @classmethod
    def register(cls, handler: NodeHandler) -> None:
        """Register a handler instance for its declared ``node_type``."""
        cls._handlers[handler.node_type] = handler

    @classmethod
    def lookup(cls, node_type: str) -> NodeHandler:
        """Look up a handler by node type name.

        Raises:
            ValueError: If ``node_type`` is not registered.
        """
        try:
            return cls._handlers[node_type]
        except KeyError:
            raise ValueError(f"Unknown node type: {node_type!r}") from None

    @classmethod
    def list_types(cls) -> list[str]:
        """Return all registered node type names."""
        return list(cls._handlers.keys())

    @classmethod
    def reset(cls) -> None:
        """Clear all registered handlers (useful for testing)."""
        cls._handlers.clear()
