"""gRPC GenerationService implementation."""

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
)
from ai.v1.generation_pb2_grpc import GenerationServiceServicer

from app.services.llm.mock import MockLLMProvider
from app.services.llm.provider import (
    CompleteEvent,
    LLMConfig,
    LLMProvider,
    Message,
    TokenEvent,
    ToolCallEvent,
)

logger = logging.getLogger(__name__)


class GenerationServicer(GenerationServiceServicer):
    """Handles LLM generation requests via gRPC server-streaming."""

    def __init__(self, llm_provider: LLMProvider | None = None) -> None:
        self._llm = llm_provider or MockLLMProvider()
        self._active_generations: dict[str, str] = {}  # generation_id -> "running"|"cancelling"

    async def StreamGenerate(
        self,
        request: GenerateRequest,
        context: grpc.aio.ServicerContext,
    ) -> AsyncIterator[GenerateResponse]:
        """Server-streaming RPC: streams tokens from LLM to caller."""
        generation_id = request.generation_id
        self._active_generations[generation_id] = "running"

        # Convert proto messages to domain messages
        messages = [
            Message(role=m.role, content=m.content)
            for m in request.messages
        ]

        config = LLMConfig(
            temperature=request.config.temperature if request.config.temperature else 0.7,
            max_tokens=request.config.max_tokens if request.config.max_tokens else 4096,
            top_p=request.config.top_p if request.config.top_p else 1.0,
            stop_sequences=list(request.config.stop_sequences),
        )

        try:
            async for event in self._llm.stream_generate(
                model=request.model or "claude-sonnet-4-6",
                messages=messages,
                config=config,
            ):
                # Check for cancellation
                if context.cancelled() or self._active_generations.get(generation_id) == "cancelling":
                    await self._llm.cancel()
                    yield GenerateResponse(
                        complete=GenerationComplete(
                            finish_reason="cancelled",
                            usage=None,
                        )
                    )
                    return

                if isinstance(event, TokenEvent):
                    yield GenerateResponse(
                        token=Token(text=event.text, index=event.index)
                    )
                elif isinstance(event, ToolCallEvent):
                    yield GenerateResponse(
                        tool_call=ProtoToolCall(
                            id=event.call_id,
                            name=event.name,
                            arguments=event.arguments,
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
            logger.exception("Generation failed: generation_id=%s", generation_id)
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
            await self._llm.cancel()
            return CancelResponse(success=True)
        return CancelResponse(success=False)
