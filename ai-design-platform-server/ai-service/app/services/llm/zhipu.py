"""ZhipuAI (GLM) LLM 提供者 — 官方 zai-sdk。"""

import asyncio
import os
from collections.abc import AsyncIterator

from app.services.llm.provider import (
    CompleteEvent,
    LLMConfig,
    LLMProvider,
    Message,
    StreamEvent,
    TokenEvent,
    ToolCallEvent,
)

# 唯一支持的模型
SUPPORTED_MODELS = frozenset({"glm-5.2"})


def _to_openai_messages(messages: list[Message]) -> list[dict[str, str]]:
    """将领域消息转换为 zai-sdk / OpenAI 格式。"""
    return [{"role": m.role, "content": m.content} for m in messages]


class ZhipuProvider(LLMProvider):
    """基于 ZhipuAI GLM-5.2 的 LLM 提供者，通过官方 zai-sdk。

    环境变量：ZHIPUAI_API_KEY
    """

    def __init__(self, api_key: str | None = None) -> None:
        from zai import ZhipuAiClient

        key = api_key or os.environ.get("ZHIPUAI_API_KEY", "")
        self._client = ZhipuAiClient(api_key=key)
        self._cancel_flag = False

    async def stream_generate(
        self,
        model: str,
        messages: list[Message],
        config: LLMConfig | None = None,
    ) -> AsyncIterator[StreamEvent]:
        if model not in SUPPORTED_MODELS:
            raise ValueError(
                f"ZhipuProvider does not support model '{model}'. "
                f"Supported: {', '.join(sorted(SUPPORTED_MODELS))}"
            )

        self._cancel_flag = False
        cfg = config or LLMConfig()

        kwargs: dict = {
            "model": model,
            "messages": _to_openai_messages(messages),
            "max_tokens": cfg.max_tokens,
            "temperature": cfg.temperature,
            "stream": True,
            "thinking": {"type": "enabled"},
        }

        index = 0
        try:
            # zai-sdk 是同步的；在 executor 中运行流式请求以保证异步安全
            loop = asyncio.get_running_loop()

            def _sync_stream():
                return self._client.chat.completions.create(**kwargs)

            stream = await loop.run_in_executor(None, _sync_stream)

            for chunk in stream:
                if self._cancel_flag:
                    yield CompleteEvent(
                        finish_reason="cancelled",
                        usage={},
                    )
                    return

                if chunk.choices and chunk.choices[0].delta:
                    delta = chunk.choices[0].delta

                    if delta.content:
                        yield TokenEvent(text=delta.content, index=index)
                        index += 1

                    if delta.tool_calls:
                        for tc in delta.tool_calls:
                            yield ToolCallEvent(
                                call_id=tc.id or "",
                                name=tc.function.name or "" if tc.function else "",
                                arguments=tc.function.arguments or "" if tc.function else "",
                            )

                if chunk.choices and chunk.choices[0].finish_reason:
                    yield CompleteEvent(
                        finish_reason="stop",
                        usage={},
                    )

            yield CompleteEvent(finish_reason="stop", usage={})

        except Exception:
            if not self._cancel_flag:
                raise
            yield CompleteEvent(finish_reason="cancelled", usage={})

    async def cancel(self) -> None:
        self._cancel_flag = True
