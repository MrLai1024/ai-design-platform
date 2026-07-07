"""HumanConfirmHandler — reads human-in-the-loop response and maps fields to state."""

from __future__ import annotations

from typing import Any

import structlog

from . import NodeHandler
from ..ir_types import NodeDef

logger = structlog.get_logger()


class HumanConfirmHandler(NodeHandler):
    """Handler for "human_confirm" workflow nodes.

    Human-in-the-loop flow:
    1. LangGraph pauses execution BEFORE this node (via interrupt_before).
    2. Backend sends ``human_confirm_required`` SSE event to the frontend.
    3. User fills in the form and POSTs the response to ``/resume``.
    4. Servicer writes the response to ``state["_human_response"]``.
    5. Graph resumes; this node's ``execute()`` reads ``_human_response``
       and maps each response field to the state key specified by the
       corresponding ``HumanConfirmField`` in the node config.
    """

    node_type = "human_confirm"

    async def execute(self, state: dict, config: dict) -> dict:
        """Read ``_human_response`` from state and map fields per config.

        Returns a dict of state updates to merge.
        """
        response = state.get("_human_response", {})
        if not response:
            logger.warning("human_confirm_no_response")
            return {}

        # config may be a raw dict or a HumanConfirmNodeConfig dataclass
        fields = (
            config["fields"]
            if isinstance(config, dict)
            else getattr(config, "fields", [])
        )

        updates: dict[str, Any] = {}
        for field in fields:
            if isinstance(field, dict):
                key = field.get("key")
            else:
                key = getattr(field, "key", None)

            if key and key in response:
                updates[key] = response[key]

        logger.info("human_confirm_merged", fields=list(updates.keys()))
        return updates

    def compile_to_langgraph(self, node_def: NodeDef):
        """Compile this node definition into a LangGraph node function.

        Returns an async callable ``(state: dict) -> dict``.
        """
        handler = self
        config = node_def.config

        async def _node_fn(state: dict) -> dict:
            return await handler.execute(state, config)

        return _node_fn
