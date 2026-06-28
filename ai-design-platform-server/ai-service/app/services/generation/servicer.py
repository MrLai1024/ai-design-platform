"""gRPC GenerationService 实现。"""

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

from app.services.llm.provider import (
    CompleteEvent,
    LLMConfig,
    LLMProvider,
    Message,
    ReasoningEvent,
    TokenEvent,
    ToolCallEvent,
)
from app.services.llm.router import resolve_provider

logger = logging.getLogger(__name__)


class GenerationServicer(GenerationServiceServicer):
    """通过 gRPC 服务器流式处理 LLM 生成请求。"""

    def __init__(self) -> None:
        self._active_generations: dict[str, str] = {}  # generation_id -> "running"|"cancelling"（生成状态）

    async def StreamGenerate(
        self,
        request: GenerateRequest,
        context: grpc.aio.ServicerContext,
    ) -> AsyncIterator[GenerateResponse]:
        """服务端流式 RPC：从 LLM 向调用者流式传输 token。"""
        generation_id = request.generation_id
        model = request.model or "glm-5.2"
        self._active_generations[generation_id] = "running"

        # 为此模型解析正确的提供者
        provider = resolve_provider(model)

        # 将 proto 消息转换为领域消息
        messages = [
            Message(role=m.role, content=m.content)
            for m in request.messages
        ]

        config = LLMConfig(
            temperature=request.config.temperature if request.config.temperature else 0.7,
            max_tokens=request.config.max_tokens if request.config.max_tokens else 4096,
            top_p=request.config.top_p if request.config.top_p else 1.0,
            stop_sequences=list(request.config.stop_sequences),
            enable_thinking=request.config.enable_thinking,
        )

        try:
            async for event in provider.stream_generate(
                model=model,
                messages=messages,
                config=config,
            ):
                # 检查是否取消
                if context.cancelled() or self._active_generations.get(generation_id) == "cancelling":
                    await provider.cancel()
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
                elif isinstance(event, ReasoningEvent):
                    yield GenerateResponse(
                        token=Token(
                            reasoning_content=event.text,
                            index=event.index,
                        )
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
            logger.exception("Generation failed: generation_id=%s model=%s", generation_id, model)
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
        """取消正在进行的生成。"""
        gid = request.generation_id
        if gid in self._active_generations:
            self._active_generations[gid] = "cancelling"
            return CancelResponse(success=True)
        return CancelResponse(success=False)
