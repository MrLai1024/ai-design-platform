"""Tests for GenerationServicer gRPC implementation."""

from unittest.mock import AsyncMock, MagicMock

import grpc
import pytest
from ai.v1.generation_pb2 import (
    CancelRequest,
    GenerateRequest,
    GenerationConfig,
    Message as ProtoMessage,
)

from app.services.generation.servicer import GenerationServicer
from app.services.llm.provider import CompleteEvent, TokenEvent


def __aiter_with_items(items: list):
    """Helper: convert a list into an async iterator."""
    async def _gen():
        for item in items:
            yield item
    return _gen()


@pytest.mark.asyncio
async def test_stream_generate_yields_tokens_and_complete():
    """StreamGenerate should convert LLM events to proto responses."""
    # Arrange: mock provider that yields one token then completes
    mock_provider = MagicMock()
    mock_provider.stream_generate = MagicMock()
    mock_provider.stream_generate.return_value = __aiter_with_items([
        TokenEvent(text="Hello", index=0),
        CompleteEvent(finish_reason="stop", usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}),
    ])

    servicer = GenerationServicer(llm_provider=mock_provider)
    context = MagicMock(spec=grpc.aio.ServicerContext)
    context.cancelled.return_value = False

    request = GenerateRequest(
        generation_id="test-123",
        model="mock-model",
        messages=[ProtoMessage(role="user", content="Hi")],
        config=GenerationConfig(temperature=0.5, max_tokens=100),
    )

    # Act
    responses = []
    async for resp in servicer.StreamGenerate(request, context):
        responses.append(resp)

    # Assert
    assert len(responses) == 2
    assert responses[0].WhichOneof("payload") == "token"
    assert responses[0].token.text == "Hello"
    assert responses[1].WhichOneof("payload") == "complete"
    assert responses[1].complete.finish_reason == "stop"
    assert responses[1].complete.usage.total_tokens == 15
