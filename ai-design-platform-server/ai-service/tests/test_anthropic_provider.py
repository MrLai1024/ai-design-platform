"""Tests for Anthropic provider. Requires ANTHROPIC_API_KEY env var."""

import os

import pytest

from app.services.llm.anthropic import AnthropicProvider
from app.services.llm.provider import CompleteEvent, Message, TokenEvent


pytestmark = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set",
)


@pytest.mark.asyncio
async def test_anthropic_streams_tokens():
    """Real Anthropic API should return tokens and a complete event."""
    provider = AnthropicProvider()
    messages = [Message(role="user", content='Say "hello world" and nothing else.')]

    events = []
    async for event in provider.stream_generate(
        model="claude-sonnet-4-6",
        messages=messages,
    ):
        events.append(event)

    tokens = [e for e in events if isinstance(e, TokenEvent)]
    completes = [e for e in events if isinstance(e, CompleteEvent)]

    assert len(tokens) > 0, "Should have at least one token"
    assert len(completes) == 1, "Should have exactly one complete event"
    assert completes[0].finish_reason in ("stop", "end_turn")
