"""GenerationServicer gRPC 实现的测试。"""

from unittest.mock import MagicMock, patch

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
    """辅助函数：将列表转换为异步迭代器。"""
    async def _gen():
        for item in items:
            yield item
    return _gen()


@pytest.mark.asyncio
async def test_stream_generate_yields_tokens_and_complete():
    """StreamGenerate 应将 LLM 事件转换为 proto 响应。"""
    # 准备：模拟提供者，先产生一个 token 然后完成
    mock_provider = MagicMock()
    mock_provider.stream_generate = MagicMock()
    mock_provider.stream_generate.return_value = __aiter_with_items([
        TokenEvent(text="Hello", index=0),
        CompleteEvent(finish_reason="stop", usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}),
    ])

    with patch("app.services.generation.servicer.resolve_provider", return_value=mock_provider):
        servicer = GenerationServicer()
        context = MagicMock(spec=grpc.aio.ServicerContext)
        context.cancelled.return_value = False

        request = GenerateRequest(
            generation_id="test-123",
            model="glm-5.2",
            messages=[ProtoMessage(role="user", content="Hi")],
            config=GenerationConfig(temperature=0.5, max_tokens=100),
        )

        # 执行
        responses = []
        async for resp in servicer.StreamGenerate(request, context):
            responses.append(resp)

    # 断言
    assert len(responses) == 2
    assert responses[0].WhichOneof("payload") == "token"
    assert responses[0].token.text == "Hello"
    assert responses[1].WhichOneof("payload") == "complete"
    assert responses[1].complete.finish_reason == "stop"
    assert responses[1].complete.usage.total_tokens == 15
