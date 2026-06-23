"""Abstract LLM provider interface."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMConfig:
    """Configuration for an LLM generation request."""
    temperature: float = 0.7
    max_tokens: int = 4096
    top_p: float = 1.0
    stop_sequences: list[str] = field(default_factory=list)


@dataclass
class Message:
    """A chat message."""
    role: str       # "system" | "user" | "assistant"
    content: str


@dataclass
class TokenEvent:
    """A single token from streaming generation."""
    text: str
    index: int


@dataclass
class ToolCallEvent:
    """A tool call request from the LLM."""
    call_id: str
    name: str
    arguments: str  # JSON string


@dataclass
class CompleteEvent:
    """Signals generation completion."""
    finish_reason: str  # "stop" | "length" | "cancelled"
    usage: dict[str, int]  # {"prompt_tokens": N, "completion_tokens": M, "total_tokens": T}


type StreamEvent = TokenEvent | ToolCallEvent | CompleteEvent


class LLMProvider(ABC):
    """Abstract base for LLM providers (OpenAI, Anthropic, etc.)."""

    @abstractmethod
    async def stream_generate(
        self,
        model: str,
        messages: list[Message],
        config: LLMConfig | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Stream tokens from the LLM. Yields TokenEvent, ToolCallEvent, or CompleteEvent."""
        ...

    @abstractmethod
    async def cancel(self) -> None:
        """Cancel the current generation."""
        ...
