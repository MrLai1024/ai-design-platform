"""gRPC GenerationService implementation — powered by LangGraph."""

import json
import logging
from typing import AsyncIterator

import grpc
from ai.v1.generation_pb2 import (
    CancelRequest,
    CancelResponse,
    GenerateRequest,
    GenerateResponse,
    GenerationComplete,
    GenerationError,
    Token,
    ToolCall as ProtoToolCall,
    Usage as ProtoUsage,
    GraphEvent as ProtoGraphEvent,
)
from ai.v1.generation_pb2_grpc import GenerationServiceServicer

from app.services.llm.provider import (
    CompleteEvent,
    LLMConfig,
    Message,
    ReasoningEvent,
    TokenEvent,
    ToolCallEvent,
)
from app.services.llm.router import resolve_provider
from .graph import GraphRunner
from .nodes import set_provider
from .state import GenerationState

logger = logging.getLogger(__name__)


class GenerationServicer(GenerationServiceServicer):
    """gRPC service for LLM generation — supports both direct chat and LangGraph pipeline."""

    def __init__(self) -> None:
        self._active_generations: dict[str, str] = {}  # generation_id -> "running"|"cancelling"
        self._active_runners: dict[str, GraphRunner] = {}

    async def StreamGenerate(
        self,
        request: GenerateRequest,
        context: grpc.aio.ServicerContext,
    ) -> AsyncIterator[GenerateResponse]:
        """Server-streaming RPC: stream tokens or LangGraph events to the caller."""
        generation_id = request.generation_id
        model = request.model or "glm-5.2"
        mode = request.metadata.get("mode", "chat")  # "chat" or "graph"

        if mode == "graph":
            async for response in self._stream_graph(generation_id, request, context):
                yield response
        else:
            async for response in self._stream_chat(generation_id, model, request, context):
                yield response

    async def _stream_graph(
        self,
        generation_id: str,
        request: GenerateRequest,
        context: grpc.aio.ServicerContext,
    ) -> AsyncIterator[GenerateResponse]:
        """Stream LangGraph pipeline events. Auto-detects resume vs fresh start."""
        self._active_generations[generation_id] = "running"
        model = request.model or "glm-5.2"
        mode = request.metadata.get("mode", "graph")

        # Set up LLM provider for the graph nodes
        provider = resolve_provider(model)
        set_provider(provider)

        # Check if this is a resume (existing runner has state)
        existing_runner = self._active_runners.get(generation_id)

        if mode == "resume" and existing_runner:
            # Resume from checkpoint
            runner = existing_runner
            try:
                async for event in runner.resume(generation_id):
                    if context.cancelled() or self._active_generations.get(generation_id) == "cancelling":
                        break
                    yield self._event_to_response(event)

                yield GenerateResponse(
                    complete=GenerationComplete(finish_reason="stop", usage=None)
                )
            except Exception as e:
                logger.exception("Graph resume failed: generation_id=%s", generation_id)
                yield GenerateResponse(
                    error=GenerationError(code="INTERNAL", message=str(e))
                )
            return

        # Check if we should skip analysis (PRD already generated via /api/v1/prd/stream)
        skip_analysis = request.metadata.get("skip_analysis") == "true"

        # Fresh start — build initial state
        user_messages = []
        user_content = ""
        for m in request.messages:
            try:
                role, content = m.role, m.content
            except AttributeError:
                role = m.get("role", "")
                content = m.get("content", "")
            user_messages.append({"role": str(role), "content": str(content)})
            if str(role) == "user" and not user_content:
                user_content = str(content)

        # If skip_analysis, pre-fill completed stages
        pre_filled_analysis = user_content if skip_analysis else None
        # Second message (assistant role) = pre-filled design_result
        pre_filled_design = None
        pre_filled_code = None
        if skip_analysis:
            if len(user_messages) >= 2 and user_messages[1].get("role") == "assistant":
                pre_filled_design = user_messages[1].get("content")
            if len(user_messages) >= 3 and user_messages[2].get("role") == "assistant":
                pre_filled_code = user_messages[2].get("content")

        state: GenerationState = {
            "requirement": user_content,
            "component_lib": request.metadata.get("component_lib", "tailwind"),
            "messages": user_messages,
            "requirements_state_json": None,
            "analysis_result": pre_filled_analysis,
            "design_result": pre_filled_design,
            "code_result": pre_filled_code,
            "review_result": None,
            "e2e_results": None,
            "e2e_test_cases": None,
            "review_passed": False,
            "review_severity": None,
            "e2e_passed": False,
            "failure_details": None,
            "qa_rounds": 0,
            "rollback_records": [],
            "rollback_count": {},
            "max_rollback_per_node": 3,
            "max_rollback_total": 10,
            "needs_manual_review": False,
            # New fields
            "stage_phase": "generating",
            "design_doc": None,
            "generated_files": {},
            "compile_errors": None,
            "review_agent_results": None,
            "review_report_html": None,
            "review_issues": None,
            "e2e_test_cases_md": None,
            "e2e_user_confirmed": False,
        }

        runner = GraphRunner()
        self._active_runners[generation_id] = runner

        try:
            async for event in runner.run(state, generation_id):
                if context.cancelled() or self._active_generations.get(generation_id) == "cancelling":
                    break
                yield self._event_to_response(event)

            yield GenerateResponse(
                complete=GenerationComplete(
                    finish_reason="stop",
                    usage=None,
                )
            )

        except Exception as e:
            logger.exception("Graph generation failed: generation_id=%s", generation_id)
            yield GenerateResponse(
                error=GenerationError(code="INTERNAL", message=str(e))
            )
        finally:
            # Only clean up if graph completed (not interrupted)
            if context.cancelled():
                self._active_generations.pop(generation_id, None)
                self._active_runners.pop(generation_id, None)

    async def _stream_chat(
        self,
        generation_id: str,
        model: str,
        request: GenerateRequest,
        context: grpc.aio.ServicerContext,
    ) -> AsyncIterator[GenerateResponse]:
        """Stream direct LLM chat (backward compatible with existing /api/v1/chat/stream)."""
        self._active_generations[generation_id] = "running"

        provider = resolve_provider(model)

        messages = [
            Message(role=m.role, content=m.content)
            for m in request.messages
        ]

        # Support enable_thinking from both config and metadata
        enable_thinking = (
            request.config.enable_thinking
            or request.metadata.get("enable_thinking") == "true"
        )
        config = LLMConfig(
            temperature=request.config.temperature if request.config.temperature else 0.7,
            max_tokens=request.config.max_tokens if request.config.max_tokens else 4096,
            top_p=request.config.top_p if request.config.top_p else 1.0,
            stop_sequences=list(request.config.stop_sequences),
            enable_thinking=enable_thinking,
        )

        try:
            async for event in provider.stream_generate(model=model, messages=messages, config=config):
                if context.cancelled() or self._active_generations.get(generation_id) == "cancelling":
                    await provider.cancel()
                    yield GenerateResponse(
                        complete=GenerationComplete(finish_reason="cancelled", usage=None)
                    )
                    return

                if isinstance(event, TokenEvent):
                    yield GenerateResponse(token=Token(text=event.text, index=event.index))
                elif isinstance(event, ReasoningEvent):
                    yield GenerateResponse(
                        token=Token(reasoning_content=event.text, index=event.index)
                    )
                elif isinstance(event, ToolCallEvent):
                    yield GenerateResponse(
                        tool_call=ProtoToolCall(
                            id=event.call_id, name=event.name, arguments=event.arguments
                        )
                    )
                elif isinstance(event, CompleteEvent):
                    yield GenerateResponse(
                        complete=GenerationComplete(
                            finish_reason=event.finish_reason,
                            usage=ProtoUsage(
                                prompt_tokens=event.usage.get("prompt_tokens", 0),
                                completion_tokens=event.usage.get("completion_tokens", 0),
                                total_tokens=event.usage.get("total_tokens", 0),
                            ) if event.usage else None,
                        )
                    )
        except Exception as e:
            logger.exception("Chat generation failed: generation_id=%s model=%s", generation_id, model)
            yield GenerateResponse(
                error=GenerationError(code="INTERNAL", message=str(e))
            )
        finally:
            self._active_generations.pop(generation_id, None)

    async def CancelGeneration(
        self,
        request: CancelRequest,
        context: grpc.aio.ServicerContext,
    ) -> CancelResponse:
        """Cancel an in-progress generation."""
        gid = request.generation_id
        if gid in self._active_generations:
            self._active_generations[gid] = "cancelling"
            return CancelResponse(success=True)
        return CancelResponse(success=False)

    def get_runner(self, generation_id: str) -> GraphRunner | None:
        """Get active GraphRunner for external operations (E2E result, confirmation)."""
        return self._active_runners.get(generation_id)

    @staticmethod
    def _event_to_response(event: dict) -> GenerateResponse:
        """Convert a GraphRunner event dict to a GenerateResponse with GraphEvent."""
        return GenerateResponse(
            graph_event=ProtoGraphEvent(
                event_type=event["event_type"],
                stage=event["stage"],
                data=json.dumps(event["data"], ensure_ascii=False),
            )
        )
