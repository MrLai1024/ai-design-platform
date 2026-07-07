"""NodeHandler ABC — base class for all workflow node type handlers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable

from ..ir_types import NodeDef


class NodeHandler(ABC):
    """Abstract base class for workflow node type handlers.

    Each concrete subclass handles one node type (e.g. "llm", "router",
    "human_confirm", "code") and provides both a runtime execution method
    and a LangGraph compilation method.
    """

    node_type: str

    @abstractmethod
    async def execute(self, state: dict, config: dict) -> dict:
        """Execute node logic. Returns partial state update to merge."""
        ...

    @abstractmethod
    def compile_to_langgraph(self, node_def: NodeDef) -> Callable:
        """Compile this node definition into a LangGraph node function.

        Returns an async callable (state: dict) -> dict.
        """
        ...


__all__ = ["NodeHandler"]
