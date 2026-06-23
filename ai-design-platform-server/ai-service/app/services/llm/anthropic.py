"""Anthropic (Claude) LLM provider implementation."""

import os
from collections.abc import AsyncIterator

from anthropic import AsyncAnthropic, AsyncMessageStream

from app.services.llm.provider import (
    CompleteEvent,
    LLMConfig,
    LLMProvider,
    Message,
    StreamEvent,
    TokenEvent,
    ToolCallEvent,
)


class AnthropicProvider(LLMProvider):
    """LLM provider backed by Anthropic Claude API with streaming."""

    def __init__(self, api_key: str | None = None) -> None:
        key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._client = AsyncAnthropic(api_key=key)
        self._cancel_flag = False

    async def stream_generate(
        self,
        model: str,
        messages: list[Message],
        config: LLMConfig | None = None,
    ) -> AsyncIterator[StreamEvent]:
        self._cancel_flag = False
        cfg = config or LLMConfig()

        # Convert messages to Anthropic format — system messages must be
        # passed via the dedicated `system` kwarg, not in the messages list.
        system_msg = ""
        anthropic_messages: list[dict[str, str]] = []
        for m in messages:
            if m.role == "system":
                system_msg = m.content
            else:
                anthropic_messages.append({"role": m.role, "content": m.content})

        kwargs: dict = {
            "model": model,
            "messages": anthropic_messages,
            "max_tokens": cfg.max_tokens,
            "temperature": cfg.temperature,
        }
        if system_msg:
            kwargs["system"] = system_msg
        if cfg.stop_sequences:
            kwargs["stop_sequences"] = cfg.stop_sequences
        if cfg.top_p != 1.0:
            kwargs["top_p"] = cfg.top_p

        # Track open tool-use blocks so we can accumulate their JSON deltas
        active_tool_calls: dict[int, dict] = {}
        token_index = 0

        try:
            async with self._client.messages.stream(**kwargs) as stream:
                # Stream is an AsyncMessageStream, iterable over raw events
                async for event in stream:
                    if self._cancel_flag:
                        # Stop consuming and signal early exit
                        yield CompleteEvent(
                            finish_reason="cancelled",
                            usage={},
                        )
                        return

                    event_type = getattr(event, "type", None)

                    # --- Text token delta ---
                    if event_type == "content_block_delta":
                        delta = event.delta
                        if getattr(delta, "type", None) == "text_delta":
                            yield TokenEvent(
                                text=delta.text or "",
                                index=token_index,
                            )
                            token_index += 1
                        elif getattr(delta, "type", None) == "input_json_delta":
                            # Accumulate partial JSON for the matching tool block
                            info = active_tool_calls.get(event.index)
                            if info is not None:
                                info["arguments"] += delta.partial_json or ""

                    # --- Block start (text or tool_use) ---
                    elif event_type == "content_block_start":
                        content_block = event.content_block
                        block_type = getattr(content_block, "type", None)
                        if block_type == "tool_use":
                            active_tool_calls[event.index] = {
                                "call_id": content_block.id,
                                "name": content_block.name,
                                "arguments": "",
                            }

                    # --- Block stop ---
                    elif event_type == "content_block_stop":
                        info = active_tool_calls.pop(event.index, None)
                        if info is not None:
                            yield ToolCallEvent(
                                call_id=info["call_id"],
                                name=info["name"],
                                arguments=info["arguments"],
                            )

                    # --- Message-level events (start / delta / stop) ---
                    elif event_type in ("message_start", "message_delta", "message_stop"):
                        pass

            # Stream ended normally
            final_text = stream.get_final_text()
            _ = final_text  # we don't return the full text; clients reassemble

            yield CompleteEvent(
                finish_reason="stop",
                usage={},
            )
        except Exception as e:
            if not self._cancel_flag:
                raise
            yield CompleteEvent(finish_reason="cancelled", usage={})

    async def cancel(self) -> None:
        self._cancel_flag = True
