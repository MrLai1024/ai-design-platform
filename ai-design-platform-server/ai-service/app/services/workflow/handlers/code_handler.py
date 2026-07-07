"""Code node handler — resolves templates and executes user code in a sandbox."""

from __future__ import annotations

from dataclasses import asdict
from typing import Callable

import structlog

from . import NodeHandler
from ..ir_types import CodeNodeConfig, NodeDef, resolve_template
from ..sandbox import SandboxExecutor

logger = structlog.get_logger()


class CodeHandler(NodeHandler):
    """Handler for "code" workflow nodes.

    Resolves {state.xxx} placeholders in the user code template against the
    current state, then executes the code in an isolated subprocess via
    :class:`SandboxExecutor`.  The captured result is stored under
    ``output_key`` in the state.
    """

    node_type = "code"

    async def execute(self, state: dict, config: dict) -> dict:
        """Execute user code in a sandboxed subprocess.

        Args:
            state: Current workflow state dict.
            config: Node configuration dict with keys ``language``, ``code``,
                    ``timeout``, and ``output_key``.

        Returns:
            A dict with ``{output_key: result}`` for merging into state.
        """
        language = config.get("language", "python")
        code = resolve_template(config.get("code", ""), state)
        timeout = config.get("timeout", 30)
        output_key = config.get("output_key", "code_output")

        logger.info(
            "code_handler_execute",
            language=language,
            code_len=len(code),
            timeout=timeout,
            output_key=output_key,
        )

        result = SandboxExecutor.execute(
            language=language,
            code=code,
            state=state,
            timeout=timeout,
        )

        # Strip internal error markers that may leak through
        result.pop("__error__", None)
        result.pop("__type__", None)

        return {output_key: result}

    def compile_to_langgraph(self, node_def: NodeDef) -> Callable:
        """Compile this node definition into a LangGraph node function.

        Returns an async callable ``(state: dict) -> dict`` that, when
        invoked, executes the code handler with the node's config.
        """
        handler = self
        config = asdict(node_def.config)

        async def _node_fn(state: dict) -> dict:
            return await handler.execute(state, config)

        return _node_fn


__all__ = ["CodeHandler"]
