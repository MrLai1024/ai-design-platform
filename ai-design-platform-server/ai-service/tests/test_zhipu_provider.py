"""ZhipuAI 提供者的测试。需要设置 ZHIPUAI_API_KEY 环境变量。"""

import os

import pytest

from app.services.llm.provider import CompleteEvent, Message, TokenEvent
from app.services.llm.zhipu import ZhipuProvider


pytestmark = pytest.mark.skipif(
    not os.environ.get("ZHIPUAI_API_KEY"),
    reason="ZHIPUAI_API_KEY not set",
)


@pytest.mark.asyncio
async def test_zhipu_streams_tokens():
    """真实的 ZhipuAI API 应返回 token 和完成事件。"""
    provider = ZhipuProvider()
    messages = [Message(role="user", content='Say "hello world" and nothing else.')]

    events = []
    async for event in provider.stream_generate(
        model="glm-5.2",
        messages=messages,
    ):
        events.append(event)

    tokens = [e for e in events if isinstance(e, TokenEvent)]
    completes = [e for e in events if isinstance(e, CompleteEvent)]

    assert len(tokens) > 0, "Should have at least one token"
    assert len(completes) >= 1, "Should have at least one complete event"
    assert completes[-1].finish_reason in ("stop", "length")
