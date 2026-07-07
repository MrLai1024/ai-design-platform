"""RouterHandler — pass-through executor that provides compile-time branch routing."""

from __future__ import annotations

from typing import Any, Callable

from . import NodeHandler
from ..ir_types import NodeDef


class RouterHandler(NodeHandler):
    """Handler for "router" nodes.

    Router nodes do no runtime work — they simply route state to one of
    several branches based on Python condition expressions.  The actual
    branching logic is compiled at graph-build time via
    ``build_router_function()`` and wired into LangGraph as a conditional
    edge by the WorkflowCompiler.
    """

    node_type = "router"

    async def execute(self, state: dict, config: dict) -> dict:
        """Pass-through — router does not modify state."""
        return {}

    def compile_to_langgraph(self, node_def: NodeDef) -> None:
        """Routers are handled specially by WorkflowCompiler — return None."""
        return None

    @staticmethod
    def build_router_function(branches: list) -> Callable:
        """Compile branch condition expressions into a router function.

        Each branch is expected to be a ``RouterBranch``-like object (or dict)
        with ``label`` and ``condition`` attributes.  The branch whose
        condition evaluates to ``True`` first wins.  A branch with condition
        ``"default"`` is used as the fallback when no other condition matches.

        Returns a callable ``(state: dict) -> str`` suitable for use as a
        LangGraph conditional edge function.
        """
        conditional: list[tuple[str, Any]] = []
        default_label: str | None = None

        for b in branches:
            label = b.get("label") if isinstance(b, dict) else getattr(b, "label", "")
            condition = b.get("condition", "") if isinstance(b, dict) else getattr(b, "condition", "")

            if condition == "default":
                default_label = label
            else:
                code = compile(condition, "<router_condition>", "eval")
                conditional.append((label, code))

        def _router_fn(state: dict) -> str:
            safe_ns = {
                "state": state,
                "bool": bool,
                "len": len,
                "str": str,
                "int": int,
                "float": float,
                "isinstance": isinstance,
                "True": True,
                "False": False,
                "None": None,
            }
            for label, cond_code in conditional:
                try:
                    if eval(cond_code, {"__builtins__": {}}, safe_ns):
                        return label
                except Exception:
                    continue
            return default_label or ""

        return _router_fn
