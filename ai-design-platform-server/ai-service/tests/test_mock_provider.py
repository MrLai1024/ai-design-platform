"""Tests for MockLLMProvider."""

import pytest

from app.services.llm.mock import MockLLMProvider
from app.services.llm.provider import (
    CompleteEvent,
    LLMConfig,
    Message,
    TokenEvent,
)


@pytest.mark.asyncio
async def test_mock_provider_streams_tokens():
    """Mock provider should yield tokens followed by a complete event."""
    provider = MockLLMProvider()
    messages = [Message(role="user", content="Hello")]

    events = []
    async for event in provider.stream_generate("mock-model", messages):
        events.append(event)

    assert len(events) >= 2  # at least one token + complete
    assert isinstance(events[0], TokenEvent)
    assert isinstance(events[-1], CompleteEvent)
    assert events[-1].finish_reason == "stop"


@pytest.mark.asyncio
async def test_mock_provider_cancellation():
    """Cancellation should yield a CompleteEvent with finish_reason='cancelled'."""
    provider = MockLLMProvider()
    messages = [Message(role="user", content="Hello" * 100)]  # long message = more tokens

    events = []
    async for event in provider.stream_generate("mock-model", messages):
        events.append(event)
        if len(events) == 1:
            await provider.cancel()
            # The next iteration should yield the cancelled CompleteEvent
            # But we need to continue the loop to collect it
            continue
        if len(events) >= 2:
            break

    assert any(
        isinstance(e, CompleteEvent) and e.finish_reason == "cancelled"
        for e in events
    )
