"""抽象的 LLM 提供者接口。"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMConfig:
    """LLM 生成请求的配置。"""
    temperature: float = 0.7
    max_tokens: int = 4096
    top_p: float = 1.0
    stop_sequences: list[str] = field(default_factory=list)
    enable_thinking: bool = False  # 用户主动开启深度思考模式
    tools: list[dict] | None = None  # OpenAI-compatible tools for function calling


@dataclass
class Message:
    """一条聊天消息。"""
    role: str       # "system" | "user" | "assistant" | "tool"（角色）
    content: str
    tool_call_id: str | None = None  # tool 消息必需（OpenAI 兼容 API 严格校验）
    tool_calls: list[dict] | None = None  # assistant 消息的标准 tool_calls 字段
    reasoning_content: str | None = None  # DeepSeek 思考模式：上一轮思考必须原样回传


@dataclass
class TokenEvent:
    """来自流式生成的单个 token。"""
    text: str
    index: int


@dataclass
class ToolCallEvent:
    """来自 LLM 的工具调用请求。"""
    call_id: str
    name: str
    arguments: str  # JSON 字符串


@dataclass
class ReasoningEvent:
    """GLM 思考过程 token — 在前端可折叠区域展示。"""
    text: str
    index: int


@dataclass
class CompleteEvent:
    """表示生成完成。"""
    finish_reason: str  # "stop" | "length" | "cancelled"（结束原因）
    usage: dict[str, int]  # {"prompt_tokens": N, "completion_tokens": M, "total_tokens": T}（用量统计）


type StreamEvent = TokenEvent | ToolCallEvent | ReasoningEvent | CompleteEvent


class LLMProvider(ABC):
    """LLM 提供者的抽象基类。"""

    @abstractmethod
    async def stream_generate(
        self,
        model: str,
        messages: list[Message],
        config: LLMConfig | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """从 LLM 流式获取 token。生成 TokenEvent、ToolCallEvent 或 CompleteEvent。"""
        ...

    @abstractmethod
    async def cancel(self) -> None:
        """取消当前生成。"""
        ...
