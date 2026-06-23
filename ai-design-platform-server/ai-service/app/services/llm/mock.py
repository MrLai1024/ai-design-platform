"""Mock LLM provider for development and testing."""

import asyncio
from collections.abc import AsyncIterator

from app.services.llm.provider import (
    CompleteEvent,
    LLMConfig,
    LLMProvider,
    Message,
    StreamEvent,
    TokenEvent,
)


class MockLLMProvider(LLMProvider):
    """Returns canned responses with simulated delay. No real API calls."""

    def __init__(self) -> None:
        self._cancelled = False

    async def stream_generate(
        self,
        model: str,
        messages: list[Message],
        config: LLMConfig | None = None,
    ) -> AsyncIterator[StreamEvent]:
        self._cancelled = False

        # Get the last user message to echo back a mock response
        user_content = ""
        for m in reversed(messages):
            if m.role == "user":
                user_content = m.content
                break

        mock_response = (
            f"你好！这是 Mock AI 的回复。你的问题是：「{user_content[:50]}...」"
            if len(user_content) > 50
            else f"你好！这是 Mock AI 的回复。你的问题是：「{user_content}」"
        )

        # Simulate token-by-token streaming with delay
        chars = list(mock_response)
        batch_size = 3  # send a few chars per token
        for i in range(0, len(chars), batch_size):
            if self._cancelled:
                yield CompleteEvent(
                    finish_reason="cancelled",
                    usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                )
                return

            token_text = "".join(chars[i : i + batch_size])
            yield TokenEvent(text=token_text, index=i // batch_size)
            await asyncio.sleep(0.05)  # simulate generation latency

        yield CompleteEvent(
            finish_reason="stop",
            usage={
                "prompt_tokens": len(user_content) // 4,
                "completion_tokens": len(mock_response) // 4,
                "total_tokens": (len(user_content) + len(mock_response)) // 4,
            },
        )

    async def cancel(self) -> None:
        self._cancelled = True
