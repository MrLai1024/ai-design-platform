"""WorkflowServicer — manages workflow CRUD, execution, and lifecycle."""

from __future__ import annotations

import uuid

import structlog

from .handlers.code_handler import CodeHandler
from .handlers.human_handler import HumanConfirmHandler
from .handlers.llm_handler import LLMHandler
from .handlers.router_handler import RouterHandler
from .ir_types import WorkflowIR
from .registry import NodeRegistry
from .runner import DynamicGraphRunner

# ---------------------------------------------------------------------------
# Auto-register all built-in handlers on import
# ---------------------------------------------------------------------------
NodeRegistry.register(LLMHandler())
NodeRegistry.register(RouterHandler())
NodeRegistry.register(HumanConfirmHandler())
NodeRegistry.register(CodeHandler())

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# In-memory stores
# ---------------------------------------------------------------------------
_workflow_store: dict[str, WorkflowIR] = {}
_active_runners: dict[str, DynamicGraphRunner] = {}


class WorkflowServicer:
    """Service layer for workflow CRUD and execution.

    All methods are ``@staticmethod`` async so they can be called directly
    from gRPC servicers or HTTP route handlers without instantiating.
    """

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    @staticmethod
    async def save(ir_dict: dict) -> dict:
        """Persist a workflow from its IR dict representation.

        Returns a dict with ``id`` and ``name``.
        """
        wf = WorkflowIR.from_dict(ir_dict)
        if not wf.id:
            wf.id = str(uuid.uuid4())
        _workflow_store[wf.id] = wf
        logger.info("workflow_saved", workflow_id=wf.id, name=wf.name)
        return {"id": wf.id, "name": wf.name}

    @staticmethod
    async def list_workflows() -> list[dict]:
        """Return a list of all saved workflows (id, name, version)."""
        return [
            {"id": wf.id, "name": wf.name, "version": wf.version}
            for wf in _workflow_store.values()
        ]

    @staticmethod
    async def get(workflow_id: str) -> dict | None:
        """Return the full IR dict for a workflow, or None if not found."""
        wf = _workflow_store.get(workflow_id)
        return wf.to_dict() if wf else None

    @staticmethod
    async def delete(workflow_id: str) -> bool:
        """Delete a workflow from the store. Returns True if it existed."""
        if workflow_id in _workflow_store:
            del _workflow_store[workflow_id]
            logger.info("workflow_deleted", workflow_id=workflow_id)
            return True
        return False

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    @staticmethod
    async def run(workflow_id: str, inputs: dict):
        """Start a workflow run and stream SSE events.

        Yields one event dict per execution milestone.
        """
        wf = _workflow_store.get(workflow_id)
        if wf is None:
            yield {
                "event_type": "node_error",
                "stage": "",
                "data": {"error": f"Workflow not found: {workflow_id}"},
            }
            return

        initial_state = {**inputs}
        for var in wf.schema.state_variables:
            if var not in initial_state:
                initial_state[var] = None
        initial_state["_human_response"] = None

        thread_id = str(uuid.uuid4())
        runner = DynamicGraphRunner()
        _active_runners[workflow_id] = runner

        logger.info(
            "workflow_run_start", workflow_id=workflow_id, thread_id=thread_id
        )
        try:
            async for event in runner.run(wf, initial_state, thread_id):
                yield event
        finally:
            logger.info(
                "workflow_run_end", workflow_id=workflow_id, thread_id=thread_id
            )

    @staticmethod
    async def resume(workflow_id: str, human_response: dict):
        """Resume a paused workflow with a human response.

        Yields the remaining execution events.
        """
        wf = _workflow_store.get(workflow_id)
        if wf is None:
            yield {
                "event_type": "node_error",
                "stage": "",
                "data": {"error": f"Workflow not found: {workflow_id}"},
            }
            return

        runner = _active_runners.get(workflow_id)
        if runner is None:
            yield {
                "event_type": "node_error",
                "stage": "",
                "data": {"error": "No active run to resume"},
            }
            return

        thread_id = str(uuid.uuid4())
        logger.info("workflow_resume", workflow_id=workflow_id)
        async for event in runner.resume(thread_id, human_response, wf):
            yield event

    @staticmethod
    async def cancel(workflow_id: str) -> bool:
        """Cancel a running workflow. Returns True if there was an active run."""
        removed = _active_runners.pop(workflow_id, None)
        if removed:
            logger.info("workflow_cancelled", workflow_id=workflow_id)
        return removed is not None
