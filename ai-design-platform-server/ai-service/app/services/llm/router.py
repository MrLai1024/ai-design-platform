"""模型路由器 — 根据模型名称选择正确的 LLM 提供者。"""

from app.services.llm.deepseek import DeepSeekProvider
from app.services.llm.provider import LLMProvider
from app.services.llm.zhipu import ZhipuProvider


def resolve_provider(model: str) -> LLMProvider:
    """根据模型名称选择提供者。

    分发规则：
    - 以 "deepseek-" 开头的模型 → DeepSeekProvider（DeepSeek API）
    - 其余模型（含 "glm-*" 及未知模型名）→ ZhipuProvider（GLM API），兜底
    """
    if model.startswith("deepseek-"):
        return DeepSeekProvider()
    return ZhipuProvider()
