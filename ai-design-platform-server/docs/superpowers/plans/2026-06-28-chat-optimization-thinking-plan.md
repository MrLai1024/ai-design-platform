# Chat Optimization & Thinking Visualization — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce AI chat TTFT (trim history, tune params) + eliminate perceived wait (stream reasoning tokens, show thinking animation) + proper async HTTP.

**Architecture:** Four-layer changes: Proto (add `reasoning_content` to Token) → Python (async httpx replacing sync zai-sdk) → Go (SSE reasoning event, message trimming, params) → Frontend (collapsible reasoning area in message bubble).

**Tech Stack:** Go 1.22 + Gin, Python 3.12 + gRPC + httpx, Vue 3 + Pinia + TypeScript, GLM-5.2 API

---

## File Structure

```
ai-design-platform-server/
├── proto/ai/v1/generation.proto          # MODIFY: add reasoning_content to Token
├── gen/go/ai/v1/generation.pb.go          # REGENERATE
├── gen/python/ai/v1/generation_pb2.py     # REGENERATE
├── gen/python/ai/v1/generation_pb2_grpc.py # REGENERATE
├── ai-service/app/services/llm/provider.py  # MODIFY: add ReasoningEvent
├── ai-service/app/services/llm/zhipu.py     # REWRITE: async httpx
├── ai-service/app/services/generation/servicer.py  # MODIFY: handle ReasoningEvent
├── gateway/internal/handler/conversation.go  # MODIFY: trim, reasoning SSE, params, system prompt
└── gateway/internal/handler/chat.go          # MODIFY: reasoning SSE, params

ai-design-platform-web/
├── packages/shared/src/types/chat.ts                      # MODIFY: add reasoning fields
├── packages/shared/src/composables/useChatStream.ts       # MODIFY: add reasoning handler
├── packages/ai-chat-app/src/stores/chatStore.ts           # MODIFY: reasoning state
├── packages/ai-chat-app/src/components/chat/ChatLayout.vue # MODIFY: wire onReasoning
└── packages/ai-chat-app/src/components/chat/ChatMessage.vue # MODIFY: collapsible reasoning area
```

---

## Layer 1: Proto Changes

### Task 1: Add reasoning_content to Token message

**Files:**
- Modify: `ai-design-platform-server/proto/ai/v1/generation.proto`

- [ ] **Step 1: Add field to proto**

Open `proto/ai/v1/generation.proto`. In the `Token` message (lines 46-49), add `reasoning_content`:

```protobuf
message Token {
  string text = 1;
  int32 index = 2;
  string reasoning_content = 3;  // GLM thinking process text
}
```

Full context — the `Token` message should read:

```protobuf
message Token {
  string text = 1;
  int32 index = 2;
  string reasoning_content = 3;  // GLM thinking process text
}
```

- [ ] **Step 2: Regenerate proto stubs**

Run from the proto directory:

```bash
cd ai-design-platform-server/proto
buf generate
```

Verify the generated files were updated:

```bash
ls -la ../gen/go/ai/v1/generation.pb.go ../gen/python/ai/v1/generation_pb2.py ../gen/python/ai/v1/generation_pb2_grpc.py
```

- [ ] **Step 3: Verify Go generated code compiles**

```bash
cd ai-design-platform-server/gateway
go build ./...
```

Expected: exit code 0, no errors. `Token` struct now has `ReasoningContent string` field.

- [ ] **Step 4: Verify Python generated code imports**

```bash
cd ai-design-platform-server/ai-service
PYTHONPATH="D:/Code/AI/ai-design-platform/ai-design-platform-server/gen/python" .venv/Scripts/python -c "from ai.v1.generation_pb2 import Token; t = Token(); print('reasoning_content' in t.DESCRIPTOR.fields_by_name)"
```

Expected: prints `True`.

- [ ] **Step 5: Commit**

```bash
cd d:/Code/AI/ai-design-platform
git add ai-design-platform-server/proto/ai/v1/generation.proto
git add ai-design-platform-server/gen/go/ai/v1/generation.pb.go
git add ai-design-platform-server/gen/python/ai/v1/generation_pb2.py
git add ai-design-platform-server/gen/python/ai/v1/generation_pb2_grpc.py
git commit -m "feat(proto): add reasoning_content field to Token message

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Layer 2: Python AI Service

### Task 2: Add ReasoningEvent to provider.py

**Files:**
- Modify: `ai-design-platform-server/ai-service/app/services/llm/provider.py`

- [ ] **Step 1: Add ReasoningEvent dataclass**

After the `ToolCallEvent` dataclass (line 37-39), insert:

```python
@dataclass
class ReasoningEvent:
    """GLM 思考过程 token — 在前端可折叠区域展示。"""
    text: str
    index: int
```

- [ ] **Step 2: Update StreamEvent type**

Change the existing line:
```python
type StreamEvent = TokenEvent | ToolCallEvent | CompleteEvent
```
To:
```python
type StreamEvent = TokenEvent | ToolCallEvent | ReasoningEvent | CompleteEvent
```

- [ ] **Step 3: Verify import**

```bash
cd ai-design-platform-server/ai-service
PYTHONPATH="D:/Code/AI/ai-design-platform/ai-design-platform-server/gen/python" .venv/Scripts/python -c "from app.services.llm.provider import ReasoningEvent, StreamEvent; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
cd d:/Code/AI/ai-design-platform
git add ai-design-platform-server/ai-service/app/services/llm/provider.py
git commit -m "feat(ai-service): add ReasoningEvent to LLM provider interface

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task 3: Rewrite zhipu.py with async httpx

**Files:**
- Modify: `ai-design-platform-server/ai-service/app/services/llm/zhipu.py`

This is the largest task. The entire `stream_generate` method is rewritten to use `httpx.AsyncClient` directly instead of the sync zai-sdk.

- [ ] **Step 1: Write the new zhipu.py**

Replace the entire file content with:

```python
"""ZhipuAI (GLM) LLM 提供者 — 直接异步 httpx 调用。"""

import asyncio
import json
import logging
import os
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.services.llm.provider import (
    CompleteEvent,
    LLMConfig,
    LLMProvider,
    Message,
    ReasoningEvent,
    StreamEvent,
    TokenEvent,
    ToolCallEvent,
)

logger = logging.getLogger(__name__)

# 唯一支持的模型
SUPPORTED_MODELS = frozenset({"glm-5.2"})

# GLM API 端点
API_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"

# 连接池配置
LIMITS = httpx.Limits(max_connections=50, max_keepalive_connections=10)

# 默认超时：连接 30s，读取 600s（10 分钟）以容纳 GLM 思考模式
DEFAULT_TIMEOUT = httpx.Timeout(timeout=600.0, connect=30.0)


def _to_openai_messages(messages: list[Message]) -> list[dict[str, str]]:
    """将领域消息转换为 OpenAI 格式。"""
    return [{"role": m.role, "content": m.content} for m in messages]


class ZhipuProvider(LLMProvider):
    """基于 ZhipuAI GLM-5.2 的 LLM 提供者，直接通过 httpx.AsyncClient 调用。

    环境变量：ZHIPUAI_API_KEY
    """

    def __init__(self, api_key: str | None = None, timeout: httpx.Timeout | None = None) -> None:
        key = api_key or os.environ.get("ZHIPUAI_API_KEY", "")
        self._api_key = key
        self._timeout = timeout or DEFAULT_TIMEOUT
        self._cancel_flag = False
        # httpx.AsyncClient 在每次 stream_generate 时创建，确保连接池复用
        self._client: httpx.AsyncClient | None = None
        logger.info("ZhipuProvider initialized with timeout connect=%.0fs read=%.0fs",
                     self._timeout.connect, self._timeout.read)

    async def _get_client(self) -> httpx.AsyncClient:
        """获取或创建共享的 httpx.AsyncClient（懒初始化）。"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=API_BASE_URL,
                timeout=self._timeout,
                limits=LIMITS,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json; charset=UTF-8",
                    "Accept": "text/event-stream",
                    "x-source-channel": "python-sdk",
                },
            )
        return self._client

    async def stream_generate(
        self,
        model: str,
        messages: list[Message],
        config: LLMConfig | None = None,
    ) -> AsyncIterator[StreamEvent]:
        if model not in SUPPORTED_MODELS:
            raise ValueError(
                f"ZhipuProvider does not support model '{model}'. "
                f"Supported: {', '.join(sorted(SUPPORTED_MODELS))}"
            )

        self._cancel_flag = False
        cfg = config or LLMConfig()

        body: dict[str, Any] = {
            "model": model,
            "messages": _to_openai_messages(messages),
            "max_tokens": cfg.max_tokens,
            "temperature": cfg.temperature,
            "stream": True,
        }
        if cfg.enable_thinking:
            body["thinking"] = {"type": "enabled"}

        t_start = time.perf_counter()
        token_count = 0
        index = 0

        try:
            client = await self._get_client()

            t_call = time.perf_counter()
            async with client.stream(
                "POST",
                "/chat/completions",
                json=body,
            ) as response:
                t_stream_ready = time.perf_counter()
                logger.info(
                    "GLM stream ready | call=%.2fs (TTFT=%.2fs) | model=%s messages=%d thinking=%s status=%d",
                    t_stream_ready - t_call,
                    t_stream_ready - t_start,
                    model,
                    len(messages),
                    cfg.enable_thinking,
                    response.status_code,
                )

                if response.status_code != 200:
                    # 读取错误体
                    error_body = await response.aread()
                    raise RuntimeError(f"GLM API returned {response.status_code}: {error_body.decode()}")

                async for line in response.aiter_lines():
                    if self._cancel_flag:
                        t_done = time.perf_counter()
                        logger.info(
                            "GLM cancelled | elapsed=%.2fs tokens=%d | model=%s",
                            t_done - t_start, token_count, model,
                        )
                        yield CompleteEvent(finish_reason="cancelled", usage={})
                        return

                    if not line.startswith("data: "):
                        continue

                    data_str = line[6:]  # strip "data: " prefix
                    if data_str == "[DONE]":
                        t_done = time.perf_counter()
                        logger.info(
                            "GLM complete | elapsed=%.2fs tokens=%d | model=%s",
                            t_done - t_start, token_count, model,
                        )
                        yield CompleteEvent(finish_reason="stop", usage={})
                        return

                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    choices = chunk.get("choices", [])
                    if not choices:
                        continue

                    delta = choices[0].get("delta", {})
                    finish_reason = choices[0].get("finish_reason")

                    # 思考过程 token（reasoning_content）
                    reasoning = delta.get("reasoning_content")
                    if reasoning:
                        yield ReasoningEvent(text=reasoning, index=index)
                        index += 1

                    # 正常内容 token
                    content = delta.get("content")
                    if content:
                        if token_count == 0:
                            t_first_token = time.perf_counter()
                            logger.info(
                                "GLM first token | delay=%.2fs | model=%s",
                                t_first_token - t_start, model,
                            )
                        yield TokenEvent(text=content, index=index)
                        token_count += 1
                        index += 1

                    # 工具调用
                    tool_calls = delta.get("tool_calls")
                    if tool_calls:
                        for tc in tool_calls:
                            func = tc.get("function", {})
                            yield ToolCallEvent(
                                call_id=tc.get("id", ""),
                                name=func.get("name", ""),
                                arguments=func.get("arguments", ""),
                            )

                    # 完成信号（带 finish_reason 的 chunk）
                    if finish_reason:
                        t_done = time.perf_counter()
                        logger.info(
                            "GLM complete | elapsed=%.2fs tokens=%d | model=%s",
                            t_done - t_start, token_count, model,
                        )
                        yield CompleteEvent(finish_reason="stop", usage={})
                        return

        except Exception:
            if not self._cancel_flag:
                raise
            t_done = time.perf_counter()
            logger.info(
                "GLM cancelled | elapsed=%.2fs tokens=%d | model=%s",
                t_done - t_start, token_count, model,
            )
            yield CompleteEvent(finish_reason="cancelled", usage={})

    async def cancel(self) -> None:
        self._cancel_flag = True

    async def close(self) -> None:
        """关闭 httpx 客户端。"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
```

- [ ] **Step 2: Verify import and basic instantiation**

```bash
cd ai-design-platform-server/ai-service
PYTHONPATH="D:/Code/AI/ai-design-platform/ai-design-platform-server/gen/python" .venv/Scripts/python -c "
from app.services.llm.zhipu import ZhipuProvider
p = ZhipuProvider(api_key='test')
print('ZhipuProvider created:', type(p).__name__)
"
```

Expected: `ZhipuProvider created: ZhipuProvider`

- [ ] **Step 3: Run existing tests (may need ZHIPUAI_API_KEY)**

```bash
cd ai-design-platform-server/ai-service
PYTHONPATH="D:/Code/AI/ai-design-platform/ai-design-platform-server/gen/python" .venv/Scripts/python -m pytest tests/test_zhipu_provider.py -v 2>&1
```

- [ ] **Step 4: Commit**

```bash
cd d:/Code/AI/ai-design-platform
git add ai-design-platform-server/ai-service/app/services/llm/zhipu.py
git commit -m "feat(ai-service): replace sync zai-sdk with async httpx + stream reasoning tokens

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task 4: Handle ReasoningEvent in servicer.py

**Files:**
- Modify: `ai-design-platform-server/ai-service/app/services/generation/servicer.py`

- [ ] **Step 1: Add import for ReasoningEvent**

In the imports (line 20-27), add `ReasoningEvent` to the import from `provider`:

```python
from app.services.llm.provider import (
    CompleteEvent,
    LLMConfig,
    LLMProvider,
    Message,
    ReasoningEvent,
    TokenEvent,
    ToolCallEvent,
)
```

- [ ] **Step 2: Add ReasoningEvent handling in the event loop**

In the `async for event in provider.stream_generate(...)` loop, after the `isinstance(event, TokenEvent)` block (after line 86), add:

```python
                elif isinstance(event, ReasoningEvent):
                    yield GenerateResponse(
                        token=Token(
                            reasoning_content=event.text,
                            index=event.index,
                        )
                    )
```

Insert it between the `TokenEvent` block and the `ToolCallEvent` block (between line 86 and line 87).

- [ ] **Step 3: Verify servicer imports correctly**

```bash
cd ai-design-platform-server/ai-service
PYTHONPATH="D:/Code/AI/ai-design-platform/ai-design-platform-server/gen/python" .venv/Scripts/python -c "
from app.services.generation.servicer import GenerationServicer
s = GenerationServicer()
print('GenerationServicer created:', type(s).__name__)
"
```

Expected: `GenerationServicer created: GenerationServicer`

- [ ] **Step 4: Commit**

```bash
cd d:/Code/AI/ai-design-platform
git add ai-design-platform-server/ai-service/app/services/generation/servicer.py
git commit -m "feat(ai-service): handle ReasoningEvent in gRPC servicer

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task 5: Restart AI service and verify timing logs

- [ ] **Step 1: Kill old AI service process**

```bash
cmd //c "for /f \"tokens=5\" %a in ('netstat -ano ^| findstr 50051') do taskkill /F /PID %a" 2>&1
```

- [ ] **Step 2: Start new AI service**

```bash
cd ai-design-platform-server/ai-service
PYTHONPATH="D:/Code/AI/ai-design-platform/ai-design-platform-server/gen/python" .venv/Scripts/python -m app.main &
sleep 3
cmd //c "netstat -ano | findstr 50051"
```

Expected: shows process listening on port 50051.

- [ ] **Step 3: Check startup log for timing confirmation**

Verify the log shows "GLM stream ready" lines with `call=` and `TTFT=` fields.

---

## Layer 3: Go Gateway

### Task 6: Update conversation.go — trim, reasoning SSE, system prompt, params

**Files:**
- Modify: `ai-design-platform-server/gateway/internal/handler/conversation.go`

- [ ] **Step 1: Add constants and trimMessages function**

Above `CreateConversation` (before line 48), add:

```go
const (
	maxHistoryRounds = 10
	systemPrompt     = `你是 AI 设计助手，专注于 UI/UX 设计、前端开发和设计系统咨询。
你可以帮助用户进行界面设计、交互设计、组件开发、样式调整等任务。
请用简洁专业的方式回答，优先给出可执行的具体建议。`
)

// trimMessages 裁剪对话历史，避免超出模型上下文窗口。
// 规则：保留首条 system 消息 + 最近 maxRounds 轮对话，中间插入省略提示。
func trimMessages(messages []store.Message, maxRounds int) []*pb.Message {
	hasSystem := len(messages) > 0 && messages[0].Role == "system"

	keepCount := maxRounds * 2 // user + assistant 对
	if hasSystem {
		keepCount++
	}

	totalAllowed := keepCount + 1 // +1 for possible system summary
	if len(messages) <= totalAllowed {
		// 无需裁剪
		out := make([]*pb.Message, len(messages))
		for i, m := range messages {
			out[i] = &pb.Message{Role: m.Role, Content: m.Content}
		}
		return out
	}

	out := make([]*pb.Message, 0, totalAllowed)

	// 保留第一条 system 消息
	if hasSystem {
		out = append(out, &pb.Message{Role: messages[0].Role, Content: messages[0].Content})
	}

	// 插入省略提示
	out = append(out, &pb.Message{Role: "system", Content: "[之前的对话已省略]"})

	// 保留最近的消息
	startIdx := len(messages) - keepCount
	if hasSystem {
		startIdx = len(messages) - (maxRounds * 2)
	}
	for _, m := range messages[startIdx:] {
		out = append(out, &pb.Message{Role: m.Role, Content: m.Content})
	}

	return out
}
```

- [ ] **Step 2: Add system prompt injection in SendMessage**

In `SendMessage`, after `slog.Info("SendMessage", ...)` and before building `pbMessages`, replace lines 106-113 (the message building block) with:

```go
	// 构建消息历史（含自动注入 system prompt 和裁剪）
	conv = h.store.Get(convID) // 添加新消息后重新获取
	rawMessages := conv.Messages

	// 如果第一条消息不是 system，则在最前面插入 system prompt
	// （仅在内存中注入，不写入 store）
	if len(rawMessages) == 0 || rawMessages[0].Role != "system" {
		rawMessages = append(
			[]store.Message{{Role: "system", Content: systemPrompt}},
			rawMessages...,
		)
	}

	// 裁剪历史消息
	pbMessages := trimMessages(rawMessages, maxHistoryRounds)
```

- [ ] **Step 3: Update GenerationConfig — max_tokens=2048**

Change line 122 from `MaxTokens: 4096` to `MaxTokens: 2048`:

```go
		Config: &pb.GenerationConfig{
			Temperature:    0.7,
			MaxTokens:      2048,
			EnableThinking: req.EnableThinking,
		},
```

- [ ] **Step 4: Update Token handling — split reasoning and text SSE events**

Replace lines 173-179 (the `GenerateResponse_Token` case) with:

```go
			case *pb.GenerateResponse_Token:
				// 思考过程 → reasoning 事件
				if payload.Token.ReasoningContent != "" {
					writeSSE(c, "reasoning", gin.H{
						"_t":    "reasoning",
						"text":  payload.Token.ReasoningContent,
						"index": payload.Token.Index,
					})
				}
				// 正常文本 → token 事件
				if payload.Token.Text != "" {
					fullContent.WriteString(payload.Token.Text)
					writeSSE(c, "token", gin.H{
						"_t":    "token",
						"text":  payload.Token.Text,
						"index": payload.Token.Index,
					})
				}
```

- [ ] **Step 5: Commit**

```bash
cd d:/Code/AI/ai-design-platform
git add ai-design-platform-server/gateway/internal/handler/conversation.go
git commit -m "feat(gateway): add reasoning SSE, message trimming, system prompt, max_tokens=2048

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task 7: Update chat.go — reasoning SSE, max_tokens=2048

**Files:**
- Modify: `ai-design-platform-server/gateway/internal/handler/chat.go`

- [ ] **Step 1: Update GenerationConfig — max_tokens=2048**

Change `MaxTokens: 4096` to `MaxTokens: 2048` on line 65.

- [ ] **Step 2: Update Token handling — same split as conversation.go**

Replace lines 103-105 (the `GenerateResponse_Token` case) with the same reasoning + token split pattern:

```go
			case *pb.GenerateResponse_Token:
				if payload.Token.ReasoningContent != "" {
					writeSSE(c, "reasoning", gin.H{
						"_t":    "reasoning",
						"text":  payload.Token.ReasoningContent,
						"index": payload.Token.Index,
					})
				}
				if payload.Token.Text != "" {
					writeSSE(c, "token", gin.H{
						"_t":    "token",
						"text":  payload.Token.Text,
						"index": payload.Token.Index,
					})
				}
```

- [ ] **Step 3: Commit**

```bash
cd d:/Code/AI/ai-design-platform
git add ai-design-platform-server/gateway/internal/handler/chat.go
git commit -m "feat(gateway): add reasoning SSE support to chat handler, max_tokens=2048

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task 8: Build and restart Go gateway

- [ ] **Step 1: Build gateway**

```bash
cd ai-design-platform-server/gateway
go build -o cmd/server/server.exe ./cmd/server
```

Expected: exit code 0, no errors.

- [ ] **Step 2: Kill old gateway and start new**

```bash
cmd //c "for /f \"tokens=5\" %a in ('netstat -ano ^| findstr \":8080.*LISTENING\"') do taskkill /F /PID %a" 2>&1
sleep 1
cd ai-design-platform-server/gateway
./cmd/server/server.exe &
sleep 2
cmd //c "netstat -ano | findstr \":8080.*LISTENING\""
```

Expected: shows new process listening on port 8080.

---

## Layer 4: Frontend

### Task 9: Add reasoning fields to types/chat.ts

**Files:**
- Modify: `ai-design-platform-web/packages/shared/src/types/chat.ts`

- [ ] **Step 1: Add reasoning fields to Message**

In the `Message` interface (lines 11-16), add optional fields:

```typescript
/** 单条消息，对应后端 Message */
export interface Message {
  id: string;
  role: 'system' | 'user' | 'assistant';
  content: string;
  created_at: string;
  reasoning_content?: string;       // NEW: 思考过程文本
  reasoning_duration_ms?: number;   // NEW: 思考耗时（毫秒）
}
```

- [ ] **Step 2: Add reasoning to StreamEvents union**

After the `token` entry in `StreamEvents` (line 65-71), add:

```typescript
/** SSE 事件联合类型 */
export interface StreamEvents {
  meta: MetaEvent;
  token: TokenEvent;
  reasoning: TokenEvent;              // NEW: 思考过程事件（复用 TokenEvent 结构）
  tool_call: ToolCallEvent;
  complete: CompleteEvent;
  error: ErrorEvent;
  done: '[DONE]';
}
```

- [ ] **Step 3: Commit**

```bash
cd d:/Code/AI/ai-design-platform
git add ai-design-platform-web/packages/shared/src/types/chat.ts
git commit -m "feat(frontend): add reasoning_content and reasoning_duration_ms to Message type

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task 10: Add reasoning handler to useChatStream.ts

**Files:**
- Modify: `ai-design-platform-web/packages/shared/src/composables/useChatStream.ts`

- [ ] **Step 1: Add onReasoning to StreamCallbacks**

In the `StreamCallbacks` interface (lines 4-11), add after `onToken`:

```typescript
export interface StreamCallbacks {
  onToken: (text: string, index: number) => void;
  onReasoning?: (text: string, index: number) => void;  // NEW
  onMeta: (meta: { generation_id: string; conversation_id?: string; message_id?: string }) => void;
  onToolCall: (tool: { id: string; name: string; arguments: string }) => void;
  onComplete: (finishReason: string) => void;
  onError: (message: string, code?: string) => void;
  onDone: () => void;
}
```

- [ ] **Step 2: Add reasoning case in event switch**

In `connect()`, after the `case 'token':` block (line 75-78), add:

```typescript
            case 'reasoning':
              callbacks.onReasoning?.(event.text as string, event.index as number);
              break;
```

- [ ] **Step 3: Commit**

```bash
cd d:/Code/AI/ai-design-platform
git add ai-design-platform-web/packages/shared/src/composables/useChatStream.ts
git commit -m "feat(frontend): add onReasoning callback and reasoning SSE event handler

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task 11: Add reasoning state to chatStore.ts

**Files:**
- Modify: `ai-design-platform-web/packages/ai-chat-app/src/stores/chatStore.ts`

- [ ] **Step 1: Add reasoning state refs**

After `enableThinking` (line 12), add:

```typescript
  const reasoningContent = ref('');
  const isReasoning = ref(false);
  const reasoningStartTime = ref(0);
```

- [ ] **Step 2: Add reasoning to displayMessages computed**

In `displayMessages` (line 14-26), add `reasoning_content` and `reasoning_duration_ms` to the virtual streaming message:

```typescript
  const displayMessages = computed<Message[]>(() => {
    if (streamingContent.value) {
      const virtual: Message = {
        id: '__streaming__',
        role: 'assistant',
        content: streamingContent.value,
        created_at: new Date().toISOString(),
        reasoning_content: reasoningContent.value || undefined,          // NEW
        reasoning_duration_ms: reasoningStartTime.value                  // NEW
          ? Date.now() - reasoningStartTime.value
          : undefined,
      };
      return [...messages.value, virtual];
    }
    return [...messages.value];
  });
```

- [ ] **Step 3: Reset reasoning state in startStreaming**

In `startStreaming()` (lines 40-44), add reasoning resets:

```typescript
  function startStreaming() {
    isStreaming.value = true;
    streamingContent.value = '';
    streamError.value = null;
    reasoningContent.value = '';        // NEW
    isReasoning.value = false;          // NEW
    reasoningStartTime.value = 0;       // NEW
  }
```

- [ ] **Step 4: Reset reasoning state in selectConversation**

In `selectConversation()` (lines 28-33), add reasoning resets:

```typescript
  function selectConversation(id: string | null, msgs: Message[] = []) {
    currentConversationId.value = id;
    messages.value = msgs;
    streamingContent.value = '';
    isStreaming.value = false;
    streamError.value = null;
    reasoningContent.value = '';        // NEW
    isReasoning.value = false;          // NEW
    reasoningStartTime.value = 0;       // NEW
  }
```

- [ ] **Step 5: Add reasoning methods**

After `appendToken()` (lines 46-48), add:

```typescript
  function appendReasoning(text: string) {
    if (!isReasoning.value) {
      isReasoning.value = true;
      reasoningStartTime.value = Date.now();
    }
    reasoningContent.value += text;
  }

  function finishReasoning() {
    isReasoning.value = false;
  }

  function getReasoningDuration(): number {
    return reasoningStartTime.value ? Date.now() - reasoningStartTime.value : 0;
  }
```

- [ ] **Step 6: Save reasoning in finishStreaming**

In `finishStreaming()` (lines 50-61), save reasoning content onto the stored message:

```typescript
  function finishStreaming(messageId: string) {
    if (streamingContent.value) {
      appendMessage({
        id: messageId,
        role: 'assistant',
        content: streamingContent.value,
        created_at: new Date().toISOString(),
        reasoning_content: reasoningContent.value || undefined,          // NEW
        reasoning_duration_ms: reasoningStartTime.value                  // NEW
          ? Date.now() - reasoningStartTime.value
          : undefined,
      });
    }
    streamingContent.value = '';
    isStreaming.value = false;
    reasoningContent.value = '';        // NEW
    isReasoning.value = false;          // NEW
  }
```

- [ ] **Step 7: Export new state and methods**

In the return block (lines 80-98), add the new exports:

```typescript
    reasoningContent,
    isReasoning,
    appendReasoning,
    finishReasoning,
    getReasoningDuration,
```

- [ ] **Step 8: Commit**

```bash
cd d:/Code/AI/ai-design-platform
git add ai-design-platform-web/packages/ai-chat-app/src/stores/chatStore.ts
git commit -m "feat(frontend): add reasoning state management to chatStore

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task 12: Wire onReasoning in ChatLayout.vue

**Files:**
- Modify: `ai-design-platform-web/packages/ai-chat-app/src/components/chat/ChatLayout.vue`

- [ ] **Step 1: Add onReasoning callback**

In the `callbacks` object (lines 41-66), add after `onToken`:

```typescript
  onReasoning(text) {
    chatStore.appendReasoning(text);
  },
```

- [ ] **Step 2: Commit**

```bash
cd d:/Code/AI/ai-design-platform
git add ai-design-platform-web/packages/ai-chat-app/src/components/chat/ChatLayout.vue
git commit -m "feat(frontend): wire onReasoning callback in ChatLayout

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task 13: Add collapsible reasoning area to ChatMessage.vue

**Files:**
- Modify: `ai-design-platform-web/packages/ai-chat-app/src/components/chat/ChatMessage.vue`

- [ ] **Step 1: Rewrite ChatMessage.vue with reasoning area**

Replace the entire file content:

```vue
<template>
  <div :class="['flex mb-4', isUser ? 'justify-end' : 'justify-start']">
    <div
      :class="[
        'max-w-[80%] rounded-lg px-4 py-3 relative group',
        isUser
          ? 'bg-indigo-600 text-white'
          : 'bg-gray-800 text-gray-200',
      ]"
    >
      <!-- 思考过程可折叠区域 -->
      <div
        v-if="hasReasoning"
        class="mb-3 border border-gray-700 rounded-md overflow-hidden"
      >
        <button
          class="w-full flex items-center gap-1.5 px-3 py-1.5 text-xs text-gray-400 hover:bg-gray-750 transition-colors"
          @click="reasoningExpanded = !reasoningExpanded"
        >
          <span class="text-sm">🧠</span>
          <span v-if="isStreaming && reasoningContent === ''">思考中...</span>
          <span v-else-if="isStreaming && reasoningContent !== ''">思考中...</span>
          <span v-else>思考过程 ({{ formattedDuration }})</span>
          <span class="ml-auto text-gray-600">{{ reasoningExpanded ? '▸ 收起' : '▸ 展开' }}</span>
        </button>
        <div
          v-show="reasoningExpanded"
          class="px-3 py-2 bg-gray-900/50 text-gray-400 text-xs font-mono leading-relaxed max-h-48 overflow-y-auto whitespace-pre-wrap"
        >
          {{ reasoningContent || '...' }}
        </div>
      </div>

      <!-- 正文内容 -->
      <MarkdownRenderer v-if="!isUser" :content="message.content || ''" />
      <p v-else class="whitespace-pre-wrap text-sm">{{ message.content }}</p>

      <span
        v-if="isStreaming"
        class="inline-block w-0.5 h-4 bg-indigo-400 ml-0.5 animate-pulse align-text-bottom"
      ></span>

      <div
        class="absolute -top-2 right-0 opacity-0 group-hover:opacity-100 transition-opacity flex gap-1"
      >
        <button
          v-if="!isUser"
          class="px-2 py-0.5 text-xs bg-gray-700 hover:bg-gray-600 text-gray-300 rounded"
          @click="copyContent"
        >
          复制
        </button>
        <button
          v-if="!isUser"
          class="px-2 py-0.5 text-xs bg-gray-700 hover:bg-gray-600 text-gray-300 rounded"
          @click="$emit('regenerate')"
        >
          重新生成
        </button>
      </div>

      <div
        v-if="message.created_at"
        class="text-[10px] text-gray-500 mt-1 opacity-0 group-hover:opacity-100 transition-opacity"
        :title="fullTime"
      >
        {{ relativeTime }}
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import type { Message } from '@ai-design/shared';
import MarkdownRenderer from '@ai-design/shared/components/MarkdownRenderer.vue';
import { useChatStore } from '@/stores/chatStore';

const props = defineProps<{
  message: Message;
  isStreaming?: boolean;
}>();

defineEmits<{
  regenerate: [];
}>();

const chatStore = useChatStore();

const reasoningExpanded = ref(true);

const isUser = computed(() => props.message.role === 'user');

// 思考内容来源：流式时来自 store，完成后来自 message 对象
const reasoningContent = computed(() => {
  if (props.isStreaming) {
    return chatStore.reasoningContent;
  }
  return props.message.reasoning_content || '';
});

const hasReasoning = computed(() => {
  return !!reasoningContent.value || (props.isStreaming && chatStore.isReasoning);
});

const formattedDuration = computed(() => {
  const ms = props.isStreaming
    ? chatStore.reasoningStartTime ? Date.now() - chatStore.reasoningStartTime : 0
    : props.message.reasoning_duration_ms || 0;
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
});

// 流式进行中自动展开，完成后 2 秒自动折叠
let autoCollapseTimer: ReturnType<typeof setTimeout> | null = null;
watch(
  () => props.isStreaming,
  (streaming) => {
    if (streaming) {
      reasoningExpanded.value = true;
    } else if (hasReasoning.value) {
      reasoningExpanded.value = true;
      autoCollapseTimer = setTimeout(() => {
        reasoningExpanded.value = false;
      }, 2000);
    }
  }
);

const fullTime = computed(() => new Date(props.message.created_at).toLocaleString('zh-CN'));

const relativeTime = computed(() => {
  const diff = Date.now() - new Date(props.message.created_at).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return '刚刚';
  if (mins < 60) return `${mins}分钟前`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}小时前`;
  return new Date(props.message.created_at).toLocaleDateString('zh-CN');
});

async function copyContent() {
  try {
    await navigator.clipboard.writeText(props.message.content);
  } catch {
    // ignore
  }
}
</script>
```

- [ ] **Step 2: Build frontend to verify compilation**

```bash
cd ai-design-platform-web
pnpm build 2>&1
```

Expected: exit code 0, no TypeScript errors.

- [ ] **Step 3: Commit**

```bash
cd d:/Code/AI/ai-design-platform
git add ai-design-platform-web/packages/ai-chat-app/src/components/chat/ChatMessage.vue
git commit -m "feat(frontend): add collapsible reasoning area to ChatMessage

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task 14: End-to-end verification

- [ ] **Step 1: Verify all services are running**

```bash
cmd //c "netstat -ano | findstr \":50051.*LISTENING\""
cmd //c "netstat -ano | findstr \":8080.*LISTENING\""
```

Expected: both 50051 (AI service) and 8080 (gateway) show LISTENING.

- [ ] **Step 2: Manual test — send a message with thinking disabled**

1. Open the chat app in browser
2. Create a new conversation  
3. Send "你好，用一句话介绍自己"
4. Observe:
   - Assistant responds within ~5s (reduced from ~6s due to max_tokens=2048)
   - No reasoning area shown (thinking disabled)
   - Response streams normally
5. Check AI service logs for "GLM stream ready" and "GLM first token" timing

- [ ] **Step 3: Manual test — send a message with thinking enabled**

1. Toggle the brain icon (enable deep thinking)
2. Send "设计一个登录页面的布局方案"
3. Observe:
   - Reasoning area appears immediately in the message bubble
   - Shows "🧠 思考中..." with streaming text
   - After reasoning completes, normal response streams below
   - 2 seconds after completion, reasoning area auto-collapses
   - User can click to expand/collapse manually
4. Check AI service logs for TTFT comparison (thinking=true vs thinking=false)

- [ ] **Step 4: Manual test — long conversation trimming**

1. Send 15+ messages in a conversation
2. Send one more message
3. Check gateway logs — verify the gRPC message count sent to AI service is ≤ 22 (1 system + 1 summary + 20 messages)
4. Verify the response is still coherent (AI has context from recent messages)

---

## Summary

| # | Task | Files | Key Change |
|---|------|-------|------------|
| 1 | Proto | 1 | Add `reasoning_content` to Token |
| 2 | Python provider | 1 | Add `ReasoningEvent` |
| 3 | Python zhipu | 1 | Sync zai-sdk → async httpx |
| 4 | Python servicer | 1 | Handle ReasoningEvent |
| 5 | AI service restart | 0 | Kill old, start new |
| 6 | Go conversation | 1 | Trim + reasoning SSE + system prompt + params |
| 7 | Go chat | 1 | Reasoning SSE + params |
| 8 | Go build & restart | 0 | Build + restart gateway |
| 9 | Frontend types | 1 | Add reasoning fields |
| 10 | Frontend useChatStream | 1 | Add reasoning SSE handler |
| 11 | Frontend chatStore | 1 | Add reasoning state |
| 12 | Frontend ChatLayout | 1 | Wire onReasoning |
| 13 | Frontend ChatMessage | 1 | Collapsible reasoning area |
| 14 | E2E verification | 0 | Manual test all flows |

**Total: 13 files modified, 1 regenerate step, 2 service restarts.**
