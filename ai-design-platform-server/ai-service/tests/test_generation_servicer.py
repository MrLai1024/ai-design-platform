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


@pytest.mark.asyncio
async def test_classify_intent_returns_intent_and_reason():
    """ClassifyIntent 应解析 LLM 意图分类结果并返回 proto 响应。"""
    from unittest.mock import AsyncMock

    from ai.v1.generation_pb2 import ClassifyIntentRequest

    mock_provider = MagicMock()

    with patch("app.services.generation.servicer.resolve_provider", return_value=mock_provider), \
         patch("app.services.generation.servicer.set_provider") as mock_set_provider, \
         patch(
             "app.services.generation.dialog._generate_with_provider",
             new_callable=AsyncMock,
             return_value='{"intent": "proceed", "reason": "用户表示可以继续"}',
         ) as mock_gen:
        servicer = GenerationServicer()
        context = MagicMock(spec=grpc.aio.ServicerContext)
        request = ClassifyIntentRequest(text="可以了", stage="analysis", generation_id="gen-1")

        resp = await servicer.ClassifyIntent(request, context)

    assert resp.intent == "proceed"
    assert resp.reason == "用户表示可以继续"
    # 分类走显式 provider 线程路径，不经过共享单例
    mock_set_provider.assert_not_called()
    assert mock_gen.await_args.args[0] is mock_provider


@pytest.mark.asyncio
async def test_classify_intent_falls_back_on_llm_error():
    """LLM 调用失败时回退 reply_qa，不向上抛错。"""
    from unittest.mock import AsyncMock

    from ai.v1.generation_pb2 import ClassifyIntentRequest

    mock_provider = MagicMock()

    with patch("app.services.generation.servicer.resolve_provider", return_value=mock_provider), \
         patch(
             "app.services.generation.dialog._generate_with_provider",
             new_callable=AsyncMock,
             side_effect=RuntimeError("provider down"),
         ):
        servicer = GenerationServicer()
        context = MagicMock(spec=grpc.aio.ServicerContext)
        request = ClassifyIntentRequest(text="你好", stage="", generation_id="gen-2")

        resp = await servicer.ClassifyIntent(request, context)

    assert resp.intent == "reply_qa"
    assert "回退" in resp.reason
