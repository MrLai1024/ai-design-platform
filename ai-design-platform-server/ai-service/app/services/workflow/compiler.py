"""WorkflowCompiler — translates WorkflowIR into a compiled LangGraph StateGraph."""

from __future__ import annotations

import time
from typing import Any

import structlog
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from .handlers.router_handler import RouterHandler
from .ir_types import NodeDef, WorkflowIR
from .registry import NodeRegistry

logger = structlog.get_logger()


class WorkflowCompiler:
    """Compiles a WorkflowIR into a runnable LangGraph StateGraph.

    Usage::

        compiler = WorkflowCompiler()
        app = compiler.compile(ir)
        # app is a CompiledStateGraph ready for app.astream(state, config)
    """

    def compile(self, ir: WorkflowIR):
        """Build and return a compiled LangGraph StateGraph from *ir*.

        Steps:
        1. Build dynamic TypedDict from ``schema.state_variables``
        2. Create ``StateGraph(DynamicState)``
        3. For each node, look up handler and call ``compile_to_langgraph()``
        4. Set entry point to first node
        5. Add regular and conditional edges
        6. Collect ``human_confirm`` node ids for ``interrupt_before``
        7. Compile with ``MemorySaver`` checkpointing

        Raises:
            ValueError: If *ir* has no nodes.
        """
        nodes = ir.nodes
        edges = ir.edges
        schema = ir.schema

        if not nodes:
            raise ValueError("Workflow must have at least one node")

        # ---- Step 1: Dynamic state type from state_variables ----
        state_type = self._build_state_type(schema.state_variables)

        # ---- Step 2: Create StateGraph ----
        workflow = StateGraph(state_type)

        # ---- Step 3: Add nodes ----
        human_confirm_ids: list[str] = []
        router_node_ids: set[str] = set()

        for node in nodes:
            if node.type == "router":
                router_node_ids.add(node.id)
                # Router does no runtime work — add a pass-through
                async def _router_pass(state: dict) -> dict:
                    return {}

                workflow.add_node(node.id, _router_pass)
            else:
                if node.type == "human_confirm":
                    human_confirm_ids.append(node.id)

                handler = NodeRegistry.lookup(node.type)
                fn = handler.compile_to_langgraph(node)
                wrapped = self._wrap_node(node, fn)
                workflow.add_node(node.id, wrapped)

        # ---- Step 4: Set entry point ----
        workflow.set_entry_point(nodes[0].id)

        # ---- Step 5: Add edges ----
        router_out_edges: dict[str, list] = {}
        for edge in edges:
            if edge.source in router_node_ids:
                router_out_edges.setdefault(edge.source, []).append(edge)
            else:
                workflow.add_edge(edge.source, edge.target)

        # ---- Step 6: Add conditional edges for routers ----
        for router_id in router_node_ids:
            router_node = next(n for n in nodes if n.id == router_id)
            branches = self._get_branches(router_node.config)
            router_fn = RouterHandler.build_router_function(branches)

            out_edges = router_out_edges.get(router_id, [])
            mapping: dict[str, Any] = {}
            for edge in out_edges:
                label = edge.condition if edge.condition else ""
                mapping[label] = edge.target
            # Safety: route unmapped results to END
            mapping[END] = END

            workflow.add_conditional_edges(router_id, router_fn, mapping)

        # ---- Step 7: Compile with checkpointer + interrupts ----
        checkpointer = MemorySaver()
        interrupt_before = human_confirm_ids if human_confirm_ids else None
        app = workflow.compile(
            checkpointer=checkpointer, interrupt_before=interrupt_before
        )

        logger.info(
            "compiler_complete",
            workflow_id=ir.id,
            nodes_count=len(nodes),
            edges_count=len(edges),
            human_confirm_count=len(human_confirm_ids),
        )
        return app

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_state_type(state_variables: list[str]) -> type:
        """Build a dynamic TypedDict class from *state_variables* for LangGraph.

        Returns a ``TypedDict`` subclass whose ``__annotations__`` describe
        every tracked state key.  If *state_variables* is empty a minimal
        TypedDict with a ``_messages`` list field is returned so that
        LangGraph has at least one key to track.
        """
        from typing import Any as AnyType, TypedDict as TypedDictCls

        annotations: dict[str, type] = {}
        for var_name in state_variables:
            annotations[var_name] = AnyType  # noqa: F821

        if not annotations:
            annotations["_messages"] = list

        return TypedDictCls("DynamicState", annotations)

    @staticmethod
    def _get_branches(config) -> list:
        """Extract branch definitions from *config* (dataclass or dict)."""
        if isinstance(config, dict):
            return config.get("branches", [])
        return getattr(config, "branches", [])

    @staticmethod
    def _wrap_node(node: NodeDef, fn):
        """Wrap a node function with logging and error handling.

        Returns an async callable ``(state: dict) -> dict``.
        """

        async def _wrapped(state: dict) -> dict:
            t0 = time.time()
            try:
                result = await fn(state)
                elapsed_ms = (time.time() - t0) * 1000
                logger.debug(
                    "node_executed",
                    node_id=node.id,
                    node_type=node.type,
                    label=node.label,
                    duration_ms=elapsed_ms,
                )
                return result
            except Exception:
                logger.exception(
                    "node_failed", node_id=node.id, node_type=node.type
                )
                raise

        return _wrapped
