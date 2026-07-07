# Chat Optimization & Thinking Visualization — Design Spec

**Status**: Approved | **Date**: 2026-06-28 | **Branch**: feature/initWeb

## Problem

Users experience 5+ seconds of blank wait after sending a chat message before seeing any response. Data from real request:

| Phase | Duration | Cause |
|-------|----------|-------|
| `call` (HTTP → stream ready) | 2.03s | GLM server queue + response headers |
| `first token` (stream ready → first content) | 3.11s | Model prefill + first token generation |
| `complete` (first token → last token) | 0.97s | 51 tokens output |
| **Total** | **6.11s** | Single message, thinking=false |

Root causes:
1. **GLM-5.2 model TTFT** — 5s even without deep thinking
2. **No user feedback during wait** — blank screen until first token arrives
3. **Full conversation history sent every request** — no trimming, prefill grows with context
4. **Sync zai-sdk blocks event loop** — doesn't scale for concurrent users
5. **max_tokens=4096** — encourages verbose output
6. **No reasoning_content streaming** — thinking tokens discarded even when thinking=enabled

## Design Goals

1. **Reduce actual TTFT** by trimming conversation history and tuning parameters
2. **Eliminate perceived blank wait** by streaming reasoning tokens and showing thinking animation
3. **Properly async** — replace sync SDK with httpx.AsyncClient for non-blocking I/O
4. **Keep compatibility** — existing chat flow (SSE events) unchanged, pure additions

---

## Layer 1: Proto Changes

### File: `proto/ai/v1/generation.proto`

Add `reasoning_content` to `Token` message:

```protobuf
message Token {
  string text = 1;
  int32 index = 2;
  string reasoning_content = 3;  // NEW: GLM thinking process text
}
```

### Impact

- `buf generate` re-runs to regenerate Go (`gen/go/`) and Python (`gen/python/`) code
- Backward compatible: empty `reasoning_content` behaves identically to current code
- No changes to other messages or service definitions

### Verification

- Proto compiles without error
- Generated Go code has `ReasoningContent` field on `Token` struct
- Generated Python code has `reasoning_content` field on `Token` class

---

## Layer 2: Python AI Service

### 2.1 Replace sync zai-sdk with async httpx

**File**: `app/services/llm/zhipu.py`

**Before** (sync, blocks thread pool):
```python
def _sync_stream():
    return self._client.chat.completions.create(**kwargs)  # zai-sdk sync
stream = await loop.run_in_executor(None, _sync_stream)     # blocks thread
for chunk in stream:                                         # blocks event loop
    ...
```

**After** (async, zero thread usage):
```python
async with httpx.AsyncClient(timeout=..., limits=...) as client:
    async with client.stream("POST", url, headers=..., json=body) as response:
        async for line in response.aiter_lines():
            if line.startswith("data: "):
                chunk = json.loads(line[6:])
                # parse and yield events
```

**Authentication**: Direct Bearer token (same as zai-sdk with `disable_token_cache=True`).

**URL**: `https://open.bigmodel.cn/api/paas/v4/chat/completions`

**Connection pool**: `httpx.Limits(max_connections=50, max_keepalive_connections=10)` — matches zai-sdk defaults.

### 2.2 New ReasoningEvent type

**File**: `app/services/llm/provider.py`

```python
@dataclass
class ReasoningEvent:
    """GLM thinking process token — shown in collapsible area."""
    text: str
    index: int

type StreamEvent = TokenEvent | ToolCallEvent | ReasoningEvent | CompleteEvent
```

### 2.3 Parse GLM reasoning_content from SSE

GLM API's streaming response format (when `thinking={"type": "enabled"}`):
```json
{
  "choices": [{
    "delta": {
      "reasoning_content": "用户想要一个登录页面...",
      "content": null
    }
  }]
}
```

When `thinking` is enabled, GLM first emits chunks with `reasoning_content` only, then switches to `content`. When `thinking` is disabled, only `content` is emitted.

Parse logic:
```python
delta = chunk["choices"][0]["delta"]

if delta.get("reasoning_content"):
    yield ReasoningEvent(text=delta["reasoning_content"], index=index)
    index += 1

if delta.get("content"):
    yield TokenEvent(text=delta["content"], index=index)
    index += 1
```

### 2.4 servicer.py changes

**File**: `app/services/generation/servicer.py`

Add handling for `ReasoningEvent`:
```python
elif isinstance(event, ReasoningEvent):
    yield GenerateResponse(
        token=Token(
            reasoning_content=event.text,
            index=event.index,
        )
    )
```

All other event types unchanged. The servicer stays as a thin translation layer.

### 2.5 Timing logs (already added)

Existing timing logs in zhipu.py remain:
- `GLM stream ready` — TTFT (HTTP response received)
- `GLM first token` — first content token with total delay
- `GLM complete` — total elapsed, token count

### Verification

- Unit test: mock GLM SSE response, verify ReasoningEvent → TokenEvent → CompleteEvent sequence
- Integration test: real ZHIPUAI_API_KEY, verify streaming output includes reasoning_content when thinking=enabled

---

## Layer 3: Go Gateway

### 3.1 New SSE event: `reasoning`

**File**: `gateway/internal/handler/conversation.go` (and `chat.go`)

In the gRPC → SSE translation loop, split `Token` handling:

```go
case *pb.GenerateResponse_Token:
    // Reasoning content → reasoning event
    if payload.Token.ReasoningContent != "" {
        writeSSE(c, "reasoning", gin.H{
            "_t":   "reasoning",
            "text": payload.Token.ReasoningContent,
            "index": payload.Token.Index,
        })
    }
    // Normal text → token event
    if payload.Token.Text != "" {
        writeSSE(c, "token", gin.H{
            "_t":   "token",
            "text": payload.Token.Text,
            "index": payload.Token.Index,
        })
        fullContent.WriteString(payload.Token.Text)
    }
```

**Important**: `fullContent` only accumulates `Text`, not `ReasoningContent`. The assistant message saved to the store contains only the final reply, not the reasoning process.

### 3.2 Message trimming

**File**: `gateway/internal/handler/conversation.go`

New function `trimMessages` called before building the gRPC request:

```go
func trimMessages(messages []store.Message, maxRounds int) []*pb.Message {
    // 1. Keep first message if it's a system prompt
    // 2. Keep last maxRounds * 2 messages (user + assistant pairs)
    // 3. If messages were trimmed, insert a system summary note
}
```

**Rules**:
| Condition | Action |
|-----------|--------|
| Total messages ≤ `maxRounds * 2 + 1` | No trimming |
| First message role == "system" | Always keep it |
| Middle messages cut | Insert `{"role": "system", "content": "[之前的对话已省略]"}` after system prompt |
| `maxRounds` | Default 10 (configurable constant) |

**Design decisions**:
- Trimming happens only when building the gRPC request — the store retains full history
- `maxRounds = 10` means at most 20 user+assistant messages + 1 system prompt = 21 messages
- The summary note is a simple fixed string, no LLM summarization needed

### 3.3 Parameter defaults

| Parameter | Old Default | New Default | Reason |
|-----------|------------|-------------|--------|
| `max_tokens` | 4096 | **2048** | Reduces verbose output, 2048 is enough for most design advice |
| `temperature` | 0.7 | 0.7 | Unchanged |
| `enable_thinking` | false | false | User must opt-in (unchanged) |

### 3.4 System prompt injection

**File**: `gateway/internal/handler/conversation.go`

In `SendMessage`, before building the gRPC message list, check if the conversation has a system prompt. If not, prepend one:

```go
const systemPrompt = `你是 AI 设计助手，专注于 UI/UX 设计、前端开发和设计系统咨询。
你可以帮助用户进行界面设计、交互设计、组件开发、样式调整等任务。
请用简洁专业的方式回答，优先给出可执行的具体建议。`
```

Only injected when the conversation's first message is not already a system message.

### 3.5 Proto regeneration

After proto changes, run:
```bash
cd ai-design-platform-server && buf generate proto
```

This regenerates both `gen/go/` and `gen/python/` code.

### Verification

- `go build ./...` compiles without errors
- Unit test for `trimMessages` with various message counts
- Integration test: full SSE stream with reasoning events

---

## Layer 4: Frontend

### 4.1 New SSE event: `reasoning`

**File**: `packages/shared/src/composables/useChatStream.ts`

Add to the event switch:
```typescript
case 'reasoning':
  callbacks.onReasoning?.(data.text, data.index)
  break
```

Add to `StreamCallbacks` interface:
```typescript
onReasoning?: (text: string, index: number) => void
```

### 4.2 Store: reasoning state

**File**: `packages/ai-chat-app/src/stores/chatStore.ts`

New state:
```typescript
const reasoningContent = ref('')
const isReasoning = ref(false)
const reasoningStartTime = ref(0)
```

New methods:
```typescript
function appendReasoning(text: string) {
  if (!isReasoning.value) {
    isReasoning.value = true
    reasoningStartTime.value = Date.now()
  }
  reasoningContent.value += text
}

function finishReasoning() {
  isReasoning.value = false
  // reasoningContent kept for display, cleared on next send
}

function getReasoningDuration(): number {
  return reasoningStartTime.value ? Date.now() - reasoningStartTime.value : 0
}
```

Reset in `startStreaming()`:
```typescript
reasoningContent.value = ''
isReasoning.value = false
reasoningStartTime.value = 0
```

### 4.3 ChatMessage: collapsible reasoning area

**File**: `packages/ai-chat-app/src/components/chat/ChatMessage.vue`

When `message.role === 'assistant'` and `message.reasoning_content` is non-empty OR `isReasoning` is true:

```
┌──────────────────────────────────────────┐
│ 🧠 思考过程 (3.2s)                  ▸ 收起 │  ← clickable header
│ ┌──────────────────────────────────────┐ │
│ │ 用户想要一个登录页面，需要考虑表单   │ │  ← gray bg, mono font, 0.85rem
│ │ 验证、响应式设计、错误状态...       │ │    max-height: 200px, overflow-y: auto
│ └──────────────────────────────────────┘ │
│                                          │
│ 这是为您设计的登录页面 HTML 代码...      │  ← normal markdown content
│                                    ▏     │  ← blinking cursor (if streaming)
└──────────────────────────────────────────┘
```

**Behavior**:
| State | Collapsed by default? | Header shows |
|-------|----------------------|--------------|
| Streaming (reasoning in progress) | **No** — expanded, content scrolling | "🧠 思考中..." + spinner |
| Streaming (content in progress) | **No** — expanded | "🧠 思考过程 (3.2s)" |
| Complete (within 2s) | **No** — expanded | "🧠 思考过程 (3.2s)" |
| Complete (after 2s) | **Yes** — auto-collapse | "🧠 思考过程 (3.2s) ▸ 展开" |

**Implementation notes**:
- Use Vue's `<Transition>` for smooth expand/collapse animation
- The header is a `<button>` with `@click="toggleReasoning"`
- During streaming, `reasoning_content` is the reactive `chatStore.reasoningContent` ref
- After streaming, `reasoning_content` is stored on the Message object

### 4.4 Message type extension

**File**: `packages/shared/src/types/chat.ts`

```typescript
export interface Message {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  created_at: string
  reasoning_content?: string         // NEW
  reasoning_duration_ms?: number     // NEW
}
```

### 4.5 ChatLayout wiring

**File**: `packages/ai-chat-app/src/components/chat/ChatLayout.vue`

In `callbacks`:
```typescript
onReasoning: (text) => {
  chatStore.appendReasoning(text)
},
```

In `onDone` / `finishStreaming`:
```typescript
// Save reasoning content to the message
const msg = chatStore.finishStreaming(msgId)
if (chatStore.reasoningContent) {
  msg.reasoning_content = chatStore.reasoningContent
  msg.reasoning_duration_ms = chatStore.getReasoningDuration()
}
```

### Verification

- Manual test: send message with thinking=enabled, verify collapsible area appears
- Manual test: send message with thinking=disabled, verify normal flow unchanged
- Auto-collapse: verify the reasoning area collapses 2s after completion

---

## Data Flow (End-to-End)

### Without thinking (existing flow, unchanged)

```
User sends message
  → POST /api/v1/conversations/:id/messages
  → Go trims history → gRPC to Python
  → Python async httpx → GLM API
  → SSE: meta
  → SSE: token × N   ← frontend appends to streamingContent
  → SSE: complete
  → SSE: done
  → Frontend: finishStreaming, save message
```

### With thinking (new flow)

```
User sends message (enable_thinking=true)
  → POST /api/v1/conversations/:id/messages
  → Go trims history → gRPC to Python
  → Python async httpx → GLM API
  → SSE: meta
  → SSE: reasoning × N  ← NEW: frontend shows "🧠 思考中..." + streaming text
  → SSE: token × N      ← frontend appends to streamingContent
  → SSE: complete
  → SSE: done
  → Frontend: finishStreaming, save message with reasoning_content
  → 2s later: reasoning area auto-collapses
```

---

## Files Changed Summary

| Layer | File | Change |
|-------|------|--------|
| Proto | `proto/ai/v1/generation.proto` | Add `reasoning_content` to Token |
| Python | `app/services/llm/provider.py` | Add `ReasoningEvent` |
| Python | `app/services/llm/zhipu.py` | Replace zai-sdk with httpx.AsyncClient, parse reasoning_content |
| Python | `app/services/generation/servicer.py` | Handle ReasoningEvent → gRPC Token |
| Go | `gateway/internal/handler/conversation.go` | SSE reasoning event, trimMessages, system prompt, max_tokens=2048 |
| Go | `gateway/internal/handler/chat.go` | SSE reasoning event, max_tokens=2048 |
| Go | `gateway/internal/handler/sse.go` | No changes (writeSSE is generic) |
| Frontend | `packages/shared/src/composables/useChatStream.ts` | Add reasoning event handling |
| Frontend | `packages/shared/src/types/chat.ts` | Add reasoning fields to Message |
| Frontend | `packages/ai-chat-app/src/stores/chatStore.ts` | Add reasoning state + methods |
| Frontend | `packages/ai-chat-app/src/components/chat/ChatLayout.vue` | Wire onReasoning callback |
| Frontend | `packages/ai-chat-app/src/components/chat/ChatMessage.vue` | Collapsible reasoning area |

## Out of Scope

- Database persistence (store remains in-memory)
- User authentication scoping
- Tool call UI rendering
- Server-side conversation summarization (uses simple truncation)
- Streaming cancellation with reasoning partial save

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Proto regeneration breaks existing code | Run `buf generate`, verify both Go and Python compile before merging |
| httpx.AsyncClient differs from zai-sdk in retry/error handling | Implement explicit retry logic in zhipu.py; keep existing error event flow |
| GLM API changes its response format | Pin API version; the `/v4/chat/completions` endpoint is stable |
| Reasoning content is very long | Cap at 2000 chars in frontend display; scrollable area with max-height |
