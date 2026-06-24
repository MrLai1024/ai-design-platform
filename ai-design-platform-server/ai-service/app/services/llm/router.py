"""模型路由器 — 根据模型名称选择正确的 LLM 提供者。"""

from app.services.llm.provider import LLMProvider
from app.services.llm.zhipu import ZhipuProvider


def resolve_provider(model: str) -> LLMProvider:
    """根据模型名称选择提供者。目前仅支持 ZhipuAI GLM。"""
    return ZhipuProvider()
