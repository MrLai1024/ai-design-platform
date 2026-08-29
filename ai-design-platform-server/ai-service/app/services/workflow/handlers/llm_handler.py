"""LLM node handler — resolves {state.xxx} templates and calls the LLM provider."""

from __future__ import annotations

import structlog

from . import NodeHandler
from ..ir_types import NodeDef, resolve_template
from ...generation.nodes import _llm_generate, set_provider
from ...llm.router import resolve_provider

logger = structlog.get_logger()


class LLMHandler(NodeHandler):
    """Handler for "llm" workflow nodes.

    Resolves {state.xxx} placeholders in system_prompt and user_prompt
    against the current state, then calls _llm_generate and stores the
    result under output_key.
    """

    node_type = "llm"

    async def execute(self, state: dict, config: dict) -> dict:
        # Support both dict and dataclass configs
        _get = config.get if isinstance(config, dict) else lambda k, d=None: getattr(config, k, d)
        system_prompt = resolve_template(_get("system_prompt", ""), state)
        user_prompt = resolve_template(_get("user_prompt", ""), state)
        model = _get("model", "deepseek-v4-pro")
        output_key = _get("output_key", "llm_output")

        logger.info(
            "llm_handler_execute",
            model=model,
            output_key=output_key,
            system_prompt_len=len(system_prompt),
            user_prompt_len=len(user_prompt),
        )

        # The generation servicer sets the provider singleton only for the
        # graph pipeline — workflow has no other setter, so each LLM node
        # resolves its own provider by model before calling.
        set_provider(resolve_provider(model))

        full_text = await _llm_generate(
            system_prompt=system_prompt,
            user_content=user_prompt,
            model=model,
        )
        return {output_key: full_text}

    def compile_to_langgraph(self, node_def: NodeDef):
        """Compile this node definition into a LangGraph node function.

        Returns an async callable (state: dict) -> dict.
        """
        handler = self
        config = node_def.config

        async def _node_fn(state: dict) -> dict:
            return await handler.execute(state, config)

        return _node_fn
