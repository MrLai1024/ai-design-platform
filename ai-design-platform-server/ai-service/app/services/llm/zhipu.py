"""ZhipuAI (GLM) LLM 提供者 — 直接异步 httpx 调用。"""

import json
import logging
import os
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.services.llm.provider import (
    CompleteEvent,
    LLMConfig,
    LLMProvider,
    Message,
    ReasoningEvent,
    StreamEvent,
    TokenEvent,
    ToolCallEvent,
)

logger = logging.getLogger(__name__)

# 唯一支持的模型
SUPPORTED_MODELS = frozenset({"glm-5.2"})

# GLM API 端点
API_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"

# 连接池配置
LIMITS = httpx.Limits(max_connections=50, max_keepalive_connections=10)

# 默认超时：连接 30s，读取 600s（10 分钟）以容纳 GLM 思考模式
DEFAULT_TIMEOUT = httpx.Timeout(timeout=600.0, connect=30.0)


def _to_openai_messages(messages: list[Message | dict]) -> list[dict[str, str]]:
    """将领域消息转换为 OpenAI 格式。支持 Message 对象和 dict。"""
    result = []
    for m in messages:
        if isinstance(m, dict):
            result.append({"role": m.get("role", ""), "content": m.get("content", "")})
        else:
            result.append({"role": m.role, "content": m.content})
    return result


class ZhipuProvider(LLMProvider):
    """基于 ZhipuAI GLM-5.2 的 LLM 提供者，直接通过 httpx.AsyncClient 调用。

    环境变量：ZHIPUAI_API_KEY
    """

    def __init__(self, api_key: str | None = None, timeout: httpx.Timeout | None = None) -> None:
        key = api_key or os.environ.get("ZHIPUAI_API_KEY", "")
        self._api_key = key
        self._timeout = timeout or DEFAULT_TIMEOUT
        self._cancel_flag = False
        self._client: httpx.AsyncClient | None = None
        logger.info("ZhipuProvider initialized with timeout connect=%.0fs read=%.0fs",
                     self._timeout.connect, self._timeout.read)

    async def _get_client(self) -> httpx.AsyncClient:
        """获取或创建共享的 httpx.AsyncClient（懒初始化）。"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=API_BASE_URL,
                timeout=self._timeout,
                limits=LIMITS,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json; charset=UTF-8",
                    "Accept": "text/event-stream",
                    "x-source-channel": "python-sdk",
                },
            )
        return self._client

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

        body: dict[str, Any] = {
            "model": model,
            "messages": _to_openai_messages(messages),
            "max_tokens": cfg.max_tokens,
            "temperature": cfg.temperature,
            "stream": True,
        }
        if cfg.enable_thinking:
            body["thinking"] = {"type": "enabled"}

        t_start = time.perf_counter()
        token_count = 0
        index = 0

        try:
            client = await self._get_client()

            t_call = time.perf_counter()
            async with client.stream(
                "POST",
                "/chat/completions",
                json=body,
            ) as response:
                t_stream_ready = time.perf_counter()
                logger.info(
                    "GLM stream ready | call=%.2fs (TTFT=%.2fs) | model=%s messages=%d thinking=%s status=%d",
                    t_stream_ready - t_call,
                    t_stream_ready - t_start,
                    model,
                    len(messages),
                    cfg.enable_thinking,
                    response.status_code,
                )

                if response.status_code != 200:
                    error_body = await response.aread()
                    raise RuntimeError(f"GLM API returned {response.status_code}: {error_body.decode()}")

                async for line in response.aiter_lines():
                    if self._cancel_flag:
                        t_done = time.perf_counter()
                        logger.info(
                            "GLM cancelled | elapsed=%.2fs tokens=%d | model=%s",
                            t_done - t_start, token_count, model,
                        )
                        yield CompleteEvent(finish_reason="cancelled", usage={})
                        return

                    if not line.startswith("data: "):
                        continue

                    data_str = line[6:]
                    if data_str == "[DONE]":
                        t_done = time.perf_counter()
                        logger.info(
                            "GLM complete | elapsed=%.2fs tokens=%d | model=%s",
                            t_done - t_start, token_count, model,
                        )
                        yield CompleteEvent(finish_reason="stop", usage={})
                        return

                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    choices = chunk.get("choices", [])
                    if not choices:
                        continue

                    delta = choices[0].get("delta", {})
                    finish_reason = choices[0].get("finish_reason")

                    # 思考过程 token（reasoning_content）
                    reasoning = delta.get("reasoning_content")
                    if reasoning:
                        yield ReasoningEvent(text=reasoning, index=index)
                        index += 1

                    # 正常内容 token
                    content = delta.get("content")
                    if content:
                        if token_count == 0:
                            t_first_token = time.perf_counter()
                            logger.info(
                                "GLM first token | delay=%.2fs | model=%s",
                                t_first_token - t_start, model,
                            )
                        yield TokenEvent(text=content, index=index)
                        token_count += 1
                        index += 1

                    # 工具调用
                    tool_calls = delta.get("tool_calls")
                    if tool_calls:
                        for tc in tool_calls:
                            func = tc.get("function", {})
                            yield ToolCallEvent(
                                call_id=tc.get("id", ""),
                                name=func.get("name", ""),
                                arguments=func.get("arguments", ""),
                            )

                    if finish_reason:
                        t_done = time.perf_counter()
                        logger.info(
                            "GLM complete | elapsed=%.2fs tokens=%d | model=%s",
                            t_done - t_start, token_count, model,
                        )
                        yield CompleteEvent(finish_reason="stop", usage={})
                        return

        except Exception:
            if not self._cancel_flag:
                raise
            t_done = time.perf_counter()
            logger.info(
                "GLM cancelled | elapsed=%.2fs tokens=%d | model=%s",
                t_done - t_start, token_count, model,
            )
            yield CompleteEvent(finish_reason="cancelled", usage={})

    async def cancel(self) -> None:
        self._cancel_flag = True

    async def close(self) -> None:
        """关闭 httpx 客户端。"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
