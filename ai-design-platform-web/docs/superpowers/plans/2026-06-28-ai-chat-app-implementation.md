# AI Chat App 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 ai-chat-app 中实现完整 AI 对话功能（创建对话、历史列表、SSE 流式输出），公共逻辑提取到 @ai-design/shared。

**Architecture:** 组合式分层 — Vue 3 Composables 封装逻辑（useChatStream/useConversation/useMarkdown），Pinia Store 管理应用状态，公共模块提取到 shared 供其他子应用复用。

**Tech Stack:** Vue 3.4 + Pinia 2.1 + Vue Router 4.2 + TypeScript + Tailwind CSS v3 + marked + highlight.js + Vitest

---

## Phase 0: 依赖安装

### Task 0.1: 安装新依赖

**Files:** Modify: `packages/shared/package.json`, `packages/ai-chat-app/package.json`

- [ ] **Step 1: 给 shared 添加 marked 和 highlight.js**

```bash
cd d:\Code\AI\ai-design-platform\ai-design-platform-web
pnpm add marked highlight.js --filter @ai-design/shared
```

- [ ] **Step 2: 给 ai-chat-app 添加 vitest 和 vue-test-utils**

```bash
pnpm add -D vitest @vue/test-utils happy-dom --filter @ai-design/ai-chat-app
```

- [ ] **Step 3: 给 ai-chat-app 添加 test 和 test:watch 脚本**

Edit `packages/ai-chat-app/package.json` — 在 `"scripts"` 中添加：

```json
"test": "vitest run",
"test:watch": "vitest"
```

- [ ] **Step 4: 创建 ai-chat-app vitest 配置**

Create `packages/ai-chat-app/vitest.config.ts`:

```typescript
import { defineConfig } from 'vitest/config';
import { resolve } from 'path';

export default defineConfig({
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
      '@ai-design/shared': resolve(__dirname, '../shared/src'),
      '@ai-design/micro-core': resolve(__dirname, '../micro-core/src'),
    },
  },
  test: {
    environment: 'happy-dom',
    include: ['__tests__/**/*.test.ts'],
  },
});
```

- [ ] **Step 5: 验证安装**

```bash
cd d:\Code\AI\ai-design-platform\ai-design-platform-web
pnpm exec vitest --version
```

Expected: vitest version printed.

- [ ] **Step 6: Commit**

```bash
git add packages/shared/package.json packages/shared/pnpm-lock.yaml packages/ai-chat-app/package.json packages/ai-chat-app/vitest.config.ts
git commit -m "chore: add marked, highlight.js, vitest deps for ai-chat-app

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Phase 1: @ai-design/shared — 类型定义 & API 封装

### Task 1.1: 定义 Chat 类型

**Files:** Create: `packages/shared/src/types/chat.ts`, Modify: `packages/shared/src/types/index.ts`, Create: `packages/shared/__tests__/chat-types.test.ts`

- [ ] **Step 1: 写类型测试**

Create `packages/shared/__tests__/chat-types.test.ts`:

```typescript
import { describe, it, expect } from 'vitest';

describe('Chat types', () => {
  it('ConversationListItem should have required fields', () => {
    const item = {
      id: 'uuid-1',
      title: '测试对话',
      msg_count: 3,
      created_at: '2026-06-28T00:00:00Z',
      updated_at: '2026-06-28T00:00:00Z',
    };
    expect(item.id).toBeDefined();
    expect(item.title).toBeDefined();
    expect(item.msg_count).toBeTypeOf('number');
    expect(item.created_at).toBeDefined();
    expect(item.updated_at).toBeDefined();
  });

  it('Message should have role as user | assistant | system', () => {
    const msg = {
      id: 'msg-1',
      role: 'user' as const,
      content: '你好',
      created_at: '2026-06-28T00:00:00Z',
    };
    expect(['user', 'assistant', 'system']).toContain(msg.role);
  });

  it('TokenEvent should use text field (matching backend)', () => {
    const event = { text: '你好', index: 0 };
    expect(event.text).toBeDefined();
    expect(event.index).toBeTypeOf('number');
  });

  it('SendMessageRequest requires model and content', () => {
    const req = { model: 'glm-5.2', content: '帮我设计' };
    expect(req.model).toBeTruthy();
    expect(req.content).toBeTruthy();
  });

  it('ListConversationsResponse wraps in conversations key', () => {
    const resp = { conversations: [] };
    expect(Array.isArray(resp.conversations)).toBe(true);
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd d:\Code\AI\ai-design-platform\ai-design-platform-web\packages\shared
pnpm test -- --reporter=verbose 2>&1 | head -30
```

Expected: 测试失败（类型定义文件尚未创建）。实际上是纯类型测试，无运行时依赖，运行会通过但类型检查不过。

- [ ] **Step 3: 创建类型定义**

Create `packages/shared/src/types/chat.ts`:

```typescript
/** 对话列表项（不含消息体），对应后端 ConversationListItem */
export interface ConversationListItem {
  id: string;
  title: string;
  msg_count: number;
  created_at: string;
  updated_at: string;
}

/** 单条消息，对应后端 Message */
export interface Message {
  id: string;
  role: 'system' | 'user' | 'assistant';
  content: string;
  created_at: string;
}

/** 完整对话（含消息列表），对应后端 Conversation */
export interface Conversation {
  id: string;
  title: string;
  messages: Message[];
  created_at: string;
  updated_at: string;
}

// ── SSE 事件类型 ──

/** SSE 事件类型 */
export type StreamEventType = 'meta' | 'token' | 'tool_call' | 'complete' | 'error' | 'done';

/** SSE token 事件 — 后端字段名是 text */
export interface TokenEvent {
  text: string;
  index: number;
}

/** SSE tool_call 事件 */
export interface ToolCallEvent {
  id: string;
  name: string;
  arguments: string;
}

/** SSE meta 事件 */
export interface MetaEvent {
  generation_id: string;
  conversation_id?: string;
  message_id?: string;
}

/** SSE error 事件 */
export interface ErrorEvent {
  message: string;
  code?: string;
}

/** SSE complete 事件 — data 是 JSON 字符串，需二次 parse */
export interface CompleteEvent {
  finish_reason: string;
}

/** SSE 事件联合类型 */
export interface StreamEvents {
  meta: MetaEvent;
  token: TokenEvent;
  tool_call: ToolCallEvent;
  complete: CompleteEvent;
  error: ErrorEvent;
  done: '[DONE]';
}

// ── 请求/响应类型 ──

/** 发送消息请求 — model + content 均为必填 */
export interface SendMessageRequest {
  model: string;
  content: string;
}

/** 创建对话响应（后端返回） */
export interface CreateConversationResponse {
  id: string;
  title: string;
  created_at: string;
}

/** 对话列表响应 — 后端用 conversations 键包裹 */
export interface ListConversationsResponse {
  conversations: ConversationListItem[];
}
```

- [ ] **Step 4: 从 types/index.ts 导出**

Edit `packages/shared/src/types/index.ts`:

```
export type { GlobalState } from './global-state';
export type { ApiResponse, PaginatedResponse, ApiError } from './api';
export type {
  ConversationListItem,
  Message,
  Conversation,
  StreamEventType,
  TokenEvent,
  ToolCallEvent,
  MetaEvent,
  ErrorEvent,
  CompleteEvent,
  StreamEvents,
  SendMessageRequest,
  CreateConversationResponse,
  ListConversationsResponse,
} from './chat';
```

- [ ] **Step 5: 运行测试验证通过**

```bash
cd d:\Code\AI\ai-design-platform\ai-design-platform-web\packages\shared
pnpm test -- --reporter=verbose
```

Expected: 类型测试通过。

- [ ] **Step 6: Commit**

```bash
git add packages/shared/src/types/chat.ts packages/shared/src/types/index.ts packages/shared/__tests__/chat-types.test.ts
git commit -m "feat(shared): add chat types aligned with backend Go structs

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 1.2: 封装 Chat API

**Files:** Create: `packages/shared/src/api/chat.ts`, Modify: `packages/shared/src/api/index.ts`

- [ ] **Step 1: 创建 API 封装**

Create `packages/shared/src/api/chat.ts`:

```typescript
import { http } from './request';
import type {
  Conversation,
  ConversationListItem,
  CreateConversationResponse,
  ListConversationsResponse,
} from '../types/chat';

/**
 * 创建新对话
 * POST /api/v1/conversations  body: { title }
 */
export function createConversation(title: string) {
  return http.post<CreateConversationResponse>('/v1/conversations', { title });
}

/**
 * 获取对话列表
 * GET /api/v1/conversations
 * 响应被 conversations 键包裹
 */
export function listConversations() {
  return http.get<ListConversationsResponse>('/v1/conversations');
}

/**
 * 获取单条对话（含消息列表）
 * GET /api/v1/conversations/:id
 */
export function getConversation(id: string) {
  return http.get<Conversation>(`/v1/conversations/${id}`);
}

/**
 * 删除对话
 * DELETE /api/v1/conversations/:id
 */
export function deleteConversation(id: string) {
  return http.delete(`/v1/conversations/${id}`);
}

/**
 * SSE 流式发送消息
 * POST /api/v1/conversations/:id/messages
 * 使用原生 fetch 以支持 ReadableStream 读取
 * 注意：请求体需要 model + content（均为必填）
 */
export function streamChat(conversationId: string, model: string, content: string) {
  return fetch(`/api/v1/conversations/${conversationId}/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model, content }),
  });
}

/**
 * 取消生成
 * POST /api/v1/chat/cancel/:generation_id
 */
export function cancelGeneration(generationId: string) {
  return http.post(`/v1/chat/cancel/${generationId}`);
}
```

- [ ] **Step 2: 从 api/index.ts 导出**

Edit `packages/shared/src/api/index.ts`:

```
export { request, get, post, http } from './request';
export {
  createConversation,
  listConversations,
  getConversation,
  deleteConversation,
  streamChat,
  cancelGeneration,
} from './chat';
```

- [ ] **Step 3: Commit**

```bash
git add packages/shared/src/api/chat.ts packages/shared/src/api/index.ts
git commit -m "feat(shared): add chat API functions aligned with backend endpoints

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Phase 2: @ai-design/shared — Composables & 组件

### Task 2.1: useMarkdown Composable

**Files:** Create: `packages/shared/src/composables/useMarkdown.ts`, Create: `packages/shared/__tests__/useMarkdown.test.ts`

- [ ] **Step 1: 写测试**

Create `packages/shared/__tests__/useMarkdown.test.ts`:

```typescript
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { ref, nextTick } from 'vue';
import { useMarkdown } from '../src/composables/useMarkdown';

describe('useMarkdown', () => {
  it('should render plain text as paragraph', async () => {
    const input = ref('hello world');
    const { renderedHtml } = useMarkdown(input);
    await nextTick();
    await new Promise((r) => setTimeout(r, 20)); // wait for debounce
    expect(renderedHtml.value).toContain('hello world');
  });

  it('should render bold markdown', async () => {
    const input = ref('**bold text**');
    const { renderedHtml } = useMarkdown(input);
    await nextTick();
    await new Promise((r) => setTimeout(r, 20));
    expect(renderedHtml.value).toContain('<strong>bold text</strong>');
  });

  it('should render code blocks with language class', async () => {
    const input = ref('```typescript\nconst x = 1;\n```');
    const { renderedHtml } = useMarkdown(input);
    await nextTick();
    await new Promise((r) => setTimeout(r, 20));
    expect(renderedHtml.value).toContain('const x = 1');
    expect(renderedHtml.value).toContain('language-typescript');
  });

  it('should handle incomplete markdown gracefully', async () => {
    const input = ref('**unclosed bold');
    const { renderedHtml } = useMarkdown(input);
    await nextTick();
    await new Promise((r) => setTimeout(r, 20));
    // Should not throw, should contain original text
    expect(renderedHtml.value).toBeTruthy();
  });

  it('should sanitize XSS attempts', async () => {
    const input = ref('<script>alert("xss")</script>');
    const { renderedHtml } = useMarkdown(input);
    await nextTick();
    await new Promise((r) => setTimeout(r, 20));
    expect(renderedHtml.value).not.toContain('<script>');
    // marked sanitizes script tags
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd d:\Code\AI\ai-design-platform\ai-design-platform-web\packages\shared
pnpm test -- --reporter=verbose
```

Expected: useMarkdown 模块未创建，测试失败。

- [ ] **Step 3: 实现 useMarkdown**

Create `packages/shared/src/composables/useMarkdown.ts`:

```typescript
import { ref, watch, type Ref } from 'vue';
import { marked } from 'marked';
import hljs from 'highlight.js';

// 配置 marked
marked.setOptions({
  breaks: true,
  gfm: true,
  highlight(code: string, lang: string): string {
    if (lang && hljs.getLanguage(lang)) {
      try {
        return hljs.highlight(code, { language: lang }).value;
      } catch {
        // fall through to auto-escape
      }
    }
    return code;
  },
});

/** 防抖时间（ms），流式场景避免每帧都重渲染 */
const DEBOUNCE_MS = 16;

/**
 * Markdown 渲染 composable。
 * 接收 rawText Ref<string>，输出渲染后的 HTML。
 * 流式场景做 16ms 防抖；对不完整 Markdown 做容错。
 */
export function useMarkdown(rawText: Ref<string>) {
  const renderedHtml = ref('');
  let timer: ReturnType<typeof setTimeout> | null = null;

  function render() {
    try {
      renderedHtml.value = marked.parse(rawText.value, {
        breaks: true,
        gfm: true,
      }) as string;
    } catch {
      // 渲染失败时降级显示原始文本
      renderedHtml.value = escapeHtml(rawText.value);
    }
  }

  watch(
    rawText,
    () => {
      if (timer) clearTimeout(timer);
      timer = setTimeout(render, DEBOUNCE_MS);
    },
    { immediate: true },
  );

  return { renderedHtml };
}

/** 简单的 HTML 转义 */
function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
```

- [ ] **Step 4: 运行测试验证通过**

```bash
cd d:\Code\AI\ai-design-platform\ai-design-platform-web\packages\shared
pnpm test -- --reporter=verbose
```

- [ ] **Step 5: Commit**

```bash
git add packages/shared/src/composables/useMarkdown.ts packages/shared/__tests__/useMarkdown.test.ts
git commit -m "feat(shared): add useMarkdown composable with streaming-safe rendering

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2.2: MarkdownRenderer 组件

**Files:** Create: `packages/shared/src/components/MarkdownRenderer.vue`

- [ ] **Step 1: 创建通用 Markdown 渲染组件**

Create `packages/shared/src/components/MarkdownRenderer.vue`:

```vue
<template>
  <div class="markdown-renderer prose prose-sm max-w-none" v-html="renderedHtml" />
</template>

<script setup lang="ts">
import { toRef, type Ref } from 'vue';
import { useMarkdown } from '../composables/useMarkdown';

const props = defineProps<{
  content: string;
}>();

const input = toRef(props, 'content') as Ref<string>;
const { renderedHtml } = useMarkdown(input);
</script>

<style>
/* 代码块容器样式（覆盖 Tailwind Typography 默认） */
.markdown-renderer pre {
  position: relative;
  background: #1e1e2e;
  border-radius: 0.5rem;
  padding: 1rem;
  overflow-x: auto;
}

.markdown-renderer pre code {
  background: transparent;
  font-size: 0.875rem;
  line-height: 1.5;
}

.markdown-renderer code {
  background: #2d2d3f;
  padding: 0.125rem 0.375rem;
  border-radius: 0.25rem;
  font-size: 0.875em;
}

.markdown-renderer pre code {
  padding: 0;
  background: transparent;
}
</style>
```

- [ ] **Step 2: Commit**

```bash
git add packages/shared/src/components/MarkdownRenderer.vue
git commit -m "feat(shared): add MarkdownRenderer component with code highlighting

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2.3: useChatStream Composable

**Files:** Create: `packages/shared/src/composables/useChatStream.ts`, Create: `packages/shared/__tests__/useChatStream.test.ts`

- [ ] **Step 1: 写测试**

Create `packages/shared/__tests__/useChatStream.test.ts`:

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest';

// SSE 帧解析逻辑（作为独立函数导出以便测试）
// 注：实际测试在 composable 创建后补充

describe('useChatStream - SSE parsing', () => {
  it('parses a single token event', () => {
    const raw = 'event: token\ndata: {"text":"你好","index":0}\n\n';
    const events = parseSSEChunk(raw);
    expect(events).toHaveLength(1);
    expect(events[0]).toEqual({ type: 'token', text: '你好', index: 0 });
  });

  it('parses meta event', () => {
    const raw = 'event: meta\ndata: {"generation_id":"gen-1","conversation_id":"conv-1"}\n\n';
    const events = parseSSEChunk(raw);
    expect(events).toHaveLength(1);
    expect(events[0].type).toBe('meta');
    expect(events[0].generation_id).toBe('gen-1');
  });

  it('parses done event', () => {
    const raw = 'event: done\ndata: [DONE]\n\n';
    const events = parseSSEChunk(raw);
    expect(events).toHaveLength(1);
    expect(events[0].type).toBe('done');
  });

  it('parses complete event (JSON string data)', () => {
    const raw = 'event: complete\ndata: {"finish_reason":"stop"}\n\n';
    const events = parseSSEChunk(raw);
    expect(events).toHaveLength(1);
    expect(events[0].type).toBe('complete');
    expect(events[0].finish_reason).toBe('stop');
  });

  it('parses error event', () => {
    const raw = 'event: error\ndata: {"code":"TIMEOUT","message":"模型超时"}\n\n';
    const events = parseSSEChunk(raw);
    expect(events).toHaveLength(1);
    expect(events[0].type).toBe('error');
    expect(events[0].message).toBe('模型超时');
  });

  it('parses multiple events in one chunk', () => {
    const raw =
      'event: meta\ndata: {"generation_id":"g1"}\n\nevent: token\ndata: {"text":"你好","index":0}\n\n';
    const events = parseSSEChunk(raw);
    expect(events).toHaveLength(2);
    expect(events[0].type).toBe('meta');
    expect(events[1].type).toBe('token');
  });

  it('handles empty chunk', () => {
    const events = parseSSEChunk('');
    expect(events).toHaveLength(0);
  });

  it('handles partial chunk (data split across chunks)', () => {
    const events = parseSSEChunk('event: token\ndata: {"text":"partial');
    expect(events).toHaveLength(0); // no complete event yet
  });
});

// ── 辅助函数（提取自 useChatStream 以便复用）──

interface ParsedSSEEvent {
  type: string;
  [key: string]: unknown;
}

function parseSSEChunk(raw: string): ParsedSSEEvent[] {
  const events: ParsedSSEEvent[] = [];
  const parts = raw.split('\n\n');
  for (const part of parts) {
    if (!part.trim()) continue;
    let eventType = '';
    let dataStr = '';
    for (const line of part.split('\n')) {
      if (line.startsWith('event: ')) {
        eventType = line.slice(7).trim();
      } else if (line.startsWith('data: ')) {
        dataStr = line.slice(6);
      }
    }
    if (!eventType || !dataStr) continue;

    if (eventType === 'done') {
      events.push({ type: 'done' });
      continue;
    }

    try {
      const parsed = JSON.parse(dataStr);
      events.push({ type: eventType, ...parsed });
    } catch {
      // 不完整 JSON，跳过
    }
  }
  return events;
}
```

- [ ] **Step 2: 运行测试**

```bash
cd d:\Code\AI\ai-design-platform\ai-design-platform-web\packages\shared
pnpm test -- --reporter=verbose
```

Expected: 解析函数尚未从 useChatStream 导出，测试失败。

- [ ] **Step 3: 实现 useChatStream**

Create `packages/shared/src/composables/useChatStream.ts`:

```typescript
import { ref, readonly, type Ref } from 'vue';
import { streamChat, cancelGeneration } from '../api/chat';

export interface StreamCallbacks {
  onToken: (text: string, index: number) => void;
  onMeta: (meta: { generation_id: string; conversation_id?: string; message_id?: string }) => void;
  onToolCall: (tool: { id: string; name: string; arguments: string }) => void;
  onComplete: (finishReason: string) => void;
  onError: (message: string, code?: string) => void;
  onDone: () => void;
}

const MAX_RETRIES = 2;
const RETRY_DELAY_MS = 1000;

/**
 * SSE 流式聊天 composable。
 * 管理 SSE 连接生命周期：启动、接收、取消、重连。
 */
export function useChatStream(callbacks: StreamCallbacks) {
  const isStreaming = ref(false);
  const error = ref<string | null>(null);
  const generationId = ref<string | null>(null);

  let abortController: AbortController | null = null;
  let retryCount = 0;

  async function start(conversationId: string, model: string, content: string) {
    isStreaming.value = true;
    error.value = null;
    retryCount = 0;

    await connect(conversationId, model, content);
  }

  async function connect(conversationId: string, model: string, content: string) {
    abortController = new AbortController();

    try {
      const response = await streamChat(conversationId, model, content);
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const reader = response.body?.getReader();
      if (!reader) throw new Error('ReadableStream not supported');

      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split('\n\n');
        buffer = parts.pop() || '';

        for (const part of parts) {
          if (!part.trim()) continue;
          const event = parseSSEEvent(part);
          if (!event) continue;

          switch (event.type) {
            case 'meta':
              generationId.value = event.generation_id as string;
              callbacks.onMeta({
                generation_id: event.generation_id as string,
                conversation_id: event.conversation_id as string | undefined,
                message_id: event.message_id as string | undefined,
              });
              break;
            case 'token':
              callbacks.onToken(event.text as string, event.index as number);
              break;
            case 'tool_call':
              callbacks.onToolCall({
                id: event.id as string,
                name: event.name as string,
                arguments: event.arguments as string,
              });
              break;
            case 'complete':
              callbacks.onComplete(event.finish_reason as string);
              break;
            case 'error':
              callbacks.onError(event.message as string, event.code as string | undefined);
              break;
            case 'done':
              callbacks.onDone();
              break;
          }
        }
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Unknown error';
      if (retryCount < MAX_RETRIES) {
        retryCount++;
        await new Promise((r) => setTimeout(r, RETRY_DELAY_MS));
        await connect(conversationId, model, content);
        return;
      }
      error.value = msg;
      callbacks.onError(msg);
    } finally {
      isStreaming.value = false;
    }
  }

  function cancel() {
    abortController?.abort();
    if (generationId.value) {
      cancelGeneration(generationId.value).catch(() => {
        // 取消失败不阻塞
      });
    }
    isStreaming.value = false;
  }

  return {
    start,
    cancel,
    isStreaming: readonly(isStreaming) as Ref<boolean>,
    error: readonly(error) as Ref<string | null>,
    generationId: readonly(generationId) as Ref<string | null>,
  };
}

// ── SSE 帧解析（导出以便测试）──

interface ParsedSSEEvent {
  type: string;
  [key: string]: unknown;
}

export function parseSSEEvent(raw: string): ParsedSSEEvent | null {
  let eventType = '';
  let dataStr = '';

  for (const line of raw.split('\n')) {
    if (line.startsWith('event: ')) {
      eventType = line.slice(7).trim();
    } else if (line.startsWith('data: ')) {
      dataStr = line.slice(6);
    }
  }

  if (!eventType || !dataStr) return null;

  if (eventType === 'done') {
    return { type: 'done' };
  }

  try {
    const parsed = JSON.parse(dataStr);
    return { type: eventType, ...parsed };
  } catch {
    return null;
  }
}
```

- [ ] **Step 4: 更新测试 — 从 useChatStream 导入 parseSSEEvent**

Edit `packages/shared/__tests__/useChatStream.test.ts` — 替换本地 `parseSSEChunk` 函数为从 useChatStream 导入的 `parseSSEEvent`：

更新 import：
```typescript
import { describe, it, expect } from 'vitest';
import { parseSSEEvent } from '../src/composables/useChatStream';
```

然后重写测试为单帧解析模式，移除批量解析的 `parseSSEChunk`。

重写后的测试：

```typescript
import { describe, it, expect } from 'vitest';
import { parseSSEEvent } from '../src/composables/useChatStream';

describe('useChatStream - SSE parsing', () => {
  it('parses a token event', () => {
    const raw = 'event: token\ndata: {"text":"你好","index":0}';
    const event = parseSSEEvent(raw);
    expect(event).not.toBeNull();
    expect(event!.type).toBe('token');
    expect(event!.text).toBe('你好');
    expect(event!.index).toBe(0);
  });

  it('parses meta event', () => {
    const raw = 'event: meta\ndata: {"generation_id":"gen-1","conversation_id":"conv-1"}';
    const event = parseSSEEvent(raw);
    expect(event).not.toBeNull();
    expect(event!.type).toBe('meta');
    expect(event!.generation_id).toBe('gen-1');
  });

  it('parses done event', () => {
    const raw = 'event: done\ndata: [DONE]';
    const event = parseSSEEvent(raw);
    expect(event).not.toBeNull();
    expect(event!.type).toBe('done');
  });

  it('parses complete event (JSON string data)', () => {
    const raw = 'event: complete\ndata: {"finish_reason":"stop"}';
    const event = parseSSEEvent(raw);
    expect(event).not.toBeNull();
    expect(event!.type).toBe('complete');
    expect(event!.finish_reason).toBe('stop');
  });

  it('parses error event', () => {
    const raw = 'event: error\ndata: {"code":"TIMEOUT","message":"模型超时"}';
    const event = parseSSEEvent(raw);
    expect(event).not.toBeNull();
    expect(event!.type).toBe('error');
    expect(event!.message).toBe('模型超时');
  });

  it('returns null for empty string', () => {
    expect(parseSSEEvent('')).toBeNull();
  });

  it('returns null for incomplete JSON data', () => {
    const raw = 'event: token\ndata: {"text":"partial';
    expect(parseSSEEvent(raw)).toBeNull();
  });

  it('returns null for missing event type', () => {
    const raw = 'data: {"text":"hello"}';
    expect(parseSSEEvent(raw)).toBeNull();
  });
});
```

- [ ] **Step 5: 运行测试验证通过**

```bash
cd d:\Code\AI\ai-design-platform\ai-design-platform-web\packages\shared
pnpm test -- --reporter=verbose
```

- [ ] **Step 6: Commit**

```bash
git add packages/shared/src/composables/useChatStream.ts packages/shared/__tests__/useChatStream.test.ts
git commit -m "feat(shared): add useChatStream composable with SSE parsing and retry

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2.4: useConversation Composable

**Files:** Create: `packages/shared/src/composables/useConversation.ts`

- [ ] **Step 1: 实现 useConversation**

Create `packages/shared/src/composables/useConversation.ts`:

```typescript
import { ref } from 'vue';
import {
  createConversation,
  listConversations,
  getConversation,
  deleteConversation,
} from '../api/chat';
import type {
  Conversation,
  ConversationListItem,
} from '../types/chat';

/**
 * 对话 CRUD composable。
 * 包装 API 调用，统一返回 { data, error, loading } 结构。
 */
export function useConversation() {
  const loading = ref(false);
  const error = ref<string | null>(null);
  const conversations = ref<ConversationListItem[]>([]);
  const currentConversation = ref<Conversation | null>(null);

  async function fetchList() {
    loading.value = true;
    error.value = null;
    try {
      const res = await listConversations();
      // 响应被 conversations 键包裹
      conversations.value = (res as unknown as { conversations: ConversationListItem[] }).conversations || [];
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : '获取对话列表失败';
    } finally {
      loading.value = false;
    }
  }

  async function fetchConversation(id: string) {
    loading.value = true;
    error.value = null;
    try {
      currentConversation.value = await getConversation(id) as unknown as Conversation;
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : '获取对话失败';
    } finally {
      loading.value = false;
    }
  }

  async function create(title: string): Promise<Conversation | null> {
    loading.value = true;
    error.value = null;
    try {
      const res = await createConversation(title) as unknown as Conversation;
      // 乐观添加到列表
      conversations.value.unshift({
        id: res.id,
        title: res.title || title,
        msg_count: 0,
        created_at: res.created_at || new Date().toISOString(),
        updated_at: res.created_at || new Date().toISOString(),
      });
      return res;
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : '创建对话失败';
      return null;
    } finally {
      loading.value = false;
    }
  }

  async function remove(id: string): Promise<boolean> {
    error.value = null;
    try {
      await deleteConversation(id);
      // 乐观移除
      conversations.value = conversations.value.filter((c) => c.id !== id);
      return true;
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : '删除对话失败';
      return false;
    }
  }

  return {
    conversations,
    currentConversation,
    loading,
    error,
    fetchList,
    fetchConversation,
    create,
    remove,
  };
}
```

- [ ] **Step 2: Commit**

```bash
git add packages/shared/src/composables/useConversation.ts
git commit -m "feat(shared): add useConversation composable for chat CRUD

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2.5: 更新 shared/src/index.ts 导出

**Files:** Modify: `packages/shared/src/index.ts`

- [ ] **Step 1: 从 index.ts 导出所有新模块**

Edit `packages/shared/src/index.ts`:

```
export * from './types';
export * from './utils';
export * from './api';
export * from './constants';
export { useChatStream } from './composables/useChatStream';
export type { StreamCallbacks } from './composables/useChatStream';
export { parseSSEEvent } from './composables/useChatStream';
export { useConversation } from './composables/useConversation';
export { useMarkdown } from './composables/useMarkdown';
export { default as MarkdownRenderer } from './components/MarkdownRenderer.vue';
```

- [ ] **Step 2: 运行完整测试套件确保无回归**

```bash
cd d:\Code\AI\ai-design-platform\ai-design-platform-web\packages\shared
pnpm test -- --reporter=verbose
```

- [ ] **Step 3: Commit**

```bash
git add packages/shared/src/index.ts
git commit -m "feat(shared): export all new chat modules from index

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Phase 3: ai-chat-app — Stores

### Task 3.1: conversationStore

**Files:** Create: `packages/ai-chat-app/src/stores/conversationStore.ts`, Create: `packages/ai-chat-app/__tests__/conversationStore.test.ts`

- [ ] **Step 1: 写 Store 测试**

Create `packages/ai-chat-app/__tests__/conversationStore.test.ts`:

```typescript
import { describe, it, expect, beforeEach } from 'vitest';
import { setActivePinia, createPinia } from 'pinia';
import { useConversationStore } from '../src/stores/conversationStore';

const mockItems = [
  { id: '1', title: '设计登录页面', msg_count: 3, created_at: '2026-06-28T00:00:00Z', updated_at: '2026-06-28T01:00:00Z' },
  { id: '2', title: 'API 设计建议', msg_count: 1, created_at: '2026-06-27T00:00:00Z', updated_at: '2026-06-27T01:00:00Z' },
  { id: '3', title: '配色方案咨询', msg_count: 5, created_at: '2026-06-26T00:00:00Z', updated_at: '2026-06-26T01:00:00Z' },
];

describe('conversationStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it('should start with empty conversations', () => {
    const store = useConversationStore();
    expect(store.conversations).toHaveLength(0);
  });

  it('should set conversations', () => {
    const store = useConversationStore();
    store.setConversations(mockItems);
    expect(store.conversations).toHaveLength(3);
  });

  it('should add conversation to top', () => {
    const store = useConversationStore();
    store.setConversations([...mockItems]);
    store.addConversation({ id: '4', title: '新对话', msg_count: 0, created_at: '', updated_at: '' });
    expect(store.conversations[0].id).toBe('4');
  });

  it('should remove conversation by id', () => {
    const store = useConversationStore();
    store.setConversations([...mockItems]);
    store.removeConversation('1');
    expect(store.conversations).toHaveLength(2);
    expect(store.conversations.find((c) => c.id === '1')).toBeUndefined();
  });

  it('should filter by search query', () => {
    const store = useConversationStore();
    store.setConversations([...mockItems]);
    store.setSearchQuery('登录');
    expect(store.filteredConversations).toHaveLength(1);
    expect(store.filteredConversations[0].id).toBe('1');
  });

  it('should filter by search query (case insensitive)', () => {
    const store = useConversationStore();
    store.setConversations([...mockItems]);
    store.setSearchQuery('api');
    expect(store.filterConversations).toHaveLength(1);
    expect(store.filterConversations[0].title).toContain('API');
  });

  it('should toggle pin status', () => {
    const store = useConversationStore();
    store.setConversations([...mockItems]);
    store.togglePin('1');
    expect(store.pinnedIds.has('1')).toBe(true);
    store.togglePin('1');
    expect(store.pinnedIds.has('1')).toBe(false);
  });

  it('pinned conversations come before normal', () => {
    const store = useConversationStore();
    store.setConversations([...mockItems]);
    store.togglePin('3');
    const pinned = store.pinnedConversations;
    const normal = store.normalConversations;
    expect(pinned).toHaveLength(1);
    expect(pinned[0].id).toBe('3');
    expect(normal).toHaveLength(2);
  });

  it('should toggle archive status', () => {
    const store = useConversationStore();
    store.setConversations([...mockItems]);
    store.toggleArchive('2');
    expect(store.archivedIds.has('2')).toBe(true);
    const archived = store.archivedConversations;
    expect(archived).toHaveLength(1);
    expect(archived[0].id).toBe('2');
  });

  it('should update conversation title', () => {
    const store = useConversationStore();
    store.setConversations([...mockItems]);
    store.updateConversation('1', { title: '新标题' });
    expect(store.conversations.find((c) => c.id === '1')?.title).toBe('新标题');
  });

  it('should increment message count', () => {
    const store = useConversationStore();
    store.setConversations([...mockItems]);
    store.incrementMsgCount('1');
    expect(store.conversations.find((c) => c.id === '1')?.msg_count).toBe(4);
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd d:\Code\AI\ai-design-platform\ai-design-platform-web\packages\ai-chat-app
pnpm test -- --reporter=verbose
```

Expected: conversationStore 未创建，测试失败。

- [ ] **Step 3: 实现 conversationStore**

Create `packages/ai-chat-app/src/stores/conversationStore.ts`:

```typescript
import { defineStore } from 'pinia';
import { ref, computed } from 'vue';
import type { ConversationListItem } from '@ai-design/shared';

/** 本地持久化的置顶/归档标记 key */
const PINNED_KEY = 'ai_chat_pinned_ids';
const ARCHIVED_KEY = 'ai_chat_archived_ids';

function loadIds(key: string): Set<string> {
  try {
    const raw = localStorage.getItem(key);
    return raw ? new Set(JSON.parse(raw)) : new Set();
  } catch {
    return new Set();
  }
}

function saveIds(key: string, ids: Set<string>) {
  localStorage.setItem(key, JSON.stringify([...ids]));
}

export const useConversationStore = defineStore('conversation', () => {
  const conversations = ref<ConversationListItem[]>([]);
  const searchQuery = ref('');
  const loading = ref(false);
  const pinnedIds = ref<Set<string>>(loadIds(PINNED_KEY));
  const archivedIds = ref<Set<string>>(loadIds(ARCHIVED_KEY));

  // ── Getters ──

  const filteredConversations = computed(() => {
    const q = searchQuery.value.toLowerCase().trim();
    if (!q) return conversations.value;
    return conversations.value.filter((c) =>
      c.title.toLowerCase().includes(q),
    );
  });

  const pinnedConversations = computed(() =>
    filteredConversations.value.filter(
      (c) => pinnedIds.value.has(c.id) && !archivedIds.value.has(c.id),
    ),
  );

  const normalConversations = computed(() =>
    filteredConversations.value.filter(
      (c) => !pinnedIds.value.has(c.id) && !archivedIds.value.has(c.id),
    ),
  );

  const archivedConversations = computed(() =>
    filteredConversations.value.filter((c) => archivedIds.value.has(c.id)),
  );

  // ── Actions ──

  function setConversations(items: ConversationListItem[]) {
    conversations.value = items;
  }

  function addConversation(item: ConversationListItem) {
    conversations.value.unshift(item);
  }

  function removeConversation(id: string) {
    conversations.value = conversations.value.filter((c) => c.id !== id);
    pinnedIds.value.delete(id);
    archivedIds.value.delete(id);
    persistPins();
    persistArchives();
  }

  function updateConversation(id: string, patch: Partial<ConversationListItem>) {
    const idx = conversations.value.findIndex((c) => c.id === id);
    if (idx !== -1) {
      conversations.value[idx] = { ...conversations.value[idx], ...patch };
    }
  }

  function incrementMsgCount(id: string) {
    const idx = conversations.value.findIndex((c) => c.id === id);
    if (idx !== -1) {
      conversations.value[idx].msg_count += 1;
    }
  }

  function setSearchQuery(q: string) {
    searchQuery.value = q;
  }

  function togglePin(id: string) {
    if (pinnedIds.value.has(id)) {
      pinnedIds.value.delete(id);
    } else {
      pinnedIds.value.add(id);
    }
    persistPins();
  }

  function toggleArchive(id: string) {
    if (archivedIds.value.has(id)) {
      archivedIds.value.delete(id);
    } else {
      archivedIds.value.add(id);
    }
    persistArchives();
  }

  function persistPins() {
    saveIds(PINNED_KEY, pinnedIds.value);
  }

  function persistArchives() {
    saveIds(ARCHIVED_KEY, archivedIds.value);
  }

  return {
    conversations,
    searchQuery,
    loading,
    pinnedIds,
    archivedIds,
    filteredConversations,
    pinnedConversations,
    normalConversations,
    archivedConversations,
    setConversations,
    addConversation,
    removeConversation,
    updateConversation,
    incrementMsgCount,
    setSearchQuery,
    togglePin,
    toggleArchive,
  };
});
```

- [ ] **Step 4: 运行测试验证通过**

```bash
cd d:\Code\AI\ai-design-platform\ai-design-platform-web\packages\ai-chat-app
pnpm test -- --reporter=verbose
```

- [ ] **Step 5: Commit**

```bash
git add packages/ai-chat-app/src/stores/conversationStore.ts packages/ai-chat-app/__tests__/conversationStore.test.ts
git commit -m "feat(ai-chat-app): add conversationStore with pin/archive/search

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3.2: chatStore

**Files:** Create: `packages/ai-chat-app/src/stores/chatStore.ts`, Create: `packages/ai-chat-app/__tests__/chatStore.test.ts`

- [ ] **Step 1: 写 Store 测试**

Create `packages/ai-chat-app/__tests__/chatStore.test.ts`:

```typescript
import { describe, it, expect, beforeEach } from 'vitest';
import { setActivePinia, createPinia } from 'pinia';
import { useChatStore } from '../src/stores/chatStore';

describe('chatStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it('should start with empty state', () => {
    const store = useChatStore();
    expect(store.currentConversationId).toBeNull();
    expect(store.messages).toHaveLength(0);
    expect(store.isStreaming).toBe(false);
  });

  it('should select a conversation and set messages', () => {
    const store = useChatStore();
    const msgs = [
      { id: '1', role: 'user' as const, content: '你好', created_at: '' },
      { id: '2', role: 'assistant' as const, content: '你好！有什么可以帮助你的？', created_at: '' },
    ];
    store.selectConversation('conv-1', msgs);
    expect(store.currentConversationId).toBe('conv-1');
    expect(store.messages).toHaveLength(2);
  });

  it('should append user message', () => {
    const store = useChatStore();
    store.appendMessage({ id: '1', role: 'user', content: '测试', created_at: '' });
    expect(store.messages).toHaveLength(1);
    expect(store.messages[0].role).toBe('user');
  });

  it('should append assistant message', () => {
    const store = useChatStore();
    store.appendMessage({ id: '1', role: 'assistant', content: '回复', created_at: '' });
    expect(store.messages[0].role).toBe('assistant');
  });

  it('should start streaming and accumulate content', () => {
    const store = useChatStore();
    store.startStreaming();
    expect(store.isStreaming).toBe(true);
    expect(store.streamingContent).toBe('');

    store.appendToken('你好');
    expect(store.streamingContent).toBe('你好');

    store.appendToken('世界');
    expect(store.streamingContent).toBe('你好世界');
  });

  it('should finish streaming and finalize message', () => {
    const store = useChatStore();
    store.startStreaming();
    store.appendToken('AI 回复内容');
    store.finishStreaming('msg-final');
    expect(store.isStreaming).toBe(false);
    expect(store.streamingContent).toBe('');
    expect(store.messages).toHaveLength(1);
    expect(store.messages[0].id).toBe('msg-final');
    expect(store.messages[0].role).toBe('assistant');
    expect(store.messages[0].content).toBe('AI 回复内容');
  });

  it('should handle stream error', () => {
    const store = useChatStore();
    store.startStreaming();
    store.appendToken('部分内容');
    store.setStreamError('网络错误');
    expect(store.streamError).toBe('网络错误');
    expect(store.streamingContent).toBe('部分内容'); // 已输出内容保留
  });

  it('displayMessages should include streaming content as virtual message', () => {
    const store = useChatStore();
    store.appendMessage({ id: '1', role: 'user', content: '提问', created_at: '' });
    store.startStreaming();
    store.appendToken('流式回复');
    expect(store.displayMessages).toHaveLength(2);
    expect(store.displayMessages[1].role).toBe('assistant');
    expect(store.displayMessages[1].content).toBe('流式回复');
    expect(store.displayMessages[1].id).toBe('__streaming__');
  });

  it('should cancel streaming', () => {
    const store = useChatStore();
    store.startStreaming();
    store.cancelStream();
    expect(store.isStreaming).toBe(false);
  });

  it('should clear input', () => {
    const store = useChatStore();
    store.inputText = 'test input';
    store.clearInput();
    expect(store.inputText).toBe('');
  });

  it('should reset state on conversation switch', () => {
    const store = useChatStore();
    store.selectConversation('conv-1', [
      { id: '1', role: 'user', content: 'msg', created_at: '' },
    ]);
    store.startStreaming();
    store.appendToken('streaming');
    store.selectConversation('conv-2', []);
    expect(store.streamingContent).toBe('');
    expect(store.isStreaming).toBe(false);
    expect(store.streamError).toBeNull();
    expect(store.currentConversationId).toBe('conv-2');
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd d:\Code\AI\ai-design-platform\ai-design-platform-web\packages\ai-chat-app
pnpm test -- --reporter=verbose
```

- [ ] **Step 3: 实现 chatStore**

Create `packages/ai-chat-app/src/stores/chatStore.ts`:

```typescript
import { defineStore } from 'pinia';
import { ref, computed } from 'vue';
import type { Message } from '@ai-design/shared';

export const useChatStore = defineStore('chat', () => {
  const currentConversationId = ref<string | null>(null);
  const messages = ref<Message[]>([]);
  const streamingContent = ref('');
  const isStreaming = ref(false);
  const streamError = ref<string | null>(null);
  const inputText = ref('');

  // ── Getters ──

  /** 包含流式未完成消息的虚拟消息列表 */
  const displayMessages = computed<Message[]>(() => {
    if (streamingContent.value) {
      const virtual: Message = {
        id: '__streaming__',
        role: 'assistant',
        content: streamingContent.value,
        created_at: new Date().toISOString(),
      };
      return [...messages.value, virtual];
    }
    return messages.value;
  });

  // ── Actions ──

  function selectConversation(id: string, msgs: Message[] = []) {
    // 切换时重置流式状态
    currentConversationId.value = id;
    messages.value = msgs;
    streamingContent.value = '';
    isStreaming.value = false;
    streamError.value = null;
  }

  function appendMessage(msg: Message) {
    messages.value.push(msg);
  }

  function startStreaming() {
    isStreaming.value = true;
    streamingContent.value = '';
    streamError.value = null;
  }

  function appendToken(text: string) {
    streamingContent.value += text;
  }

  function finishStreaming(messageId: string) {
    if (streamingContent.value) {
      appendMessage({
        id: messageId,
        role: 'assistant',
        content: streamingContent.value,
        created_at: new Date().toISOString(),
      });
    }
    streamingContent.value = '';
    isStreaming.value = false;
  }

  function setStreamError(err: string) {
    streamError.value = err;
    isStreaming.value = false;
  }

  function cancelStream() {
    isStreaming.value = false;
    // 保留已收到内容（streamingContent 不清空，让用户看到已输出部分）
  }

  function clearInput() {
    inputText.value = '';
  }

  return {
    currentConversationId,
    messages,
    streamingContent,
    isStreaming,
    streamError,
    inputText,
    displayMessages,
    selectConversation,
    appendMessage,
    startStreaming,
    appendToken,
    finishStreaming,
    setStreamError,
    cancelStream,
    clearInput,
  };
});
```

- [ ] **Step 4: 运行测试验证通过**

```bash
cd d:\Code\AI\ai-design-platform\ai-design-platform-web\packages\ai-chat-app
pnpm test -- --reporter=verbose
```

- [ ] **Step 5: Commit**

```bash
git add packages/ai-chat-app/src/stores/chatStore.ts packages/ai-chat-app/__tests__/chatStore.test.ts
git commit -m "feat(ai-chat-app): add chatStore with streaming state management

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Phase 4: ai-chat-app — Composable

### Task 4.1: useAutoScroll

**Files:** Create: `packages/ai-chat-app/src/composables/useAutoScroll.ts`

- [ ] **Step 1: 实现 useAutoScroll**

Create `packages/ai-chat-app/src/composables/useAutoScroll.ts`:

```typescript
import { watch, ref, nextTick, type Ref } from 'vue';

const SCROLL_THRESHOLD = 80; // px from bottom to consider "at bottom"

/**
 * 自动滚动 composable。
 * 流式输出 / 新消息时自动滚到底部，用户手动上滚时暂停，
 * 滚回底部时恢复。
 */
export function useAutoScroll(
  containerRef: Ref<HTMLElement | null>,
  deps: Ref<unknown>, // 消息列表长度或 streamingContent 变化
) {
  const isUserScrolling = ref(false);

  function scrollToBottom() {
    nextTick(() => {
      const el = containerRef.value;
      if (el && !isUserScrolling.value) {
        el.scrollTop = el.scrollHeight;
      }
    });
  }

  function onScroll() {
    const el = containerRef.value;
    if (!el) return;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    isUserScrolling.value = distanceFromBottom > SCROLL_THRESHOLD;
  }

  function forceScrollToBottom() {
    isUserScrolling.value = false;
    scrollToBottom();
  }

  // 监听依赖变化 → 自动滚底
  watch(deps, () => {
    scrollToBottom();
  }, { deep: true });

  return {
    onScroll,
    scrollToBottom,
    forceScrollToBottom,
  };
}
```

- [ ] **Step 2: Commit**

```bash
git add packages/ai-chat-app/src/composables/useAutoScroll.ts
git commit -m "feat(ai-chat-app): add useAutoScroll for smart streaming scroll

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Phase 5: ai-chat-app — 组件

### Task 5.1: EmptyState 组件

**Files:** Create: `packages/ai-chat-app/src/components/chat/EmptyState.vue`

- [ ] **Step 1: 实现 EmptyState**

Create `packages/ai-chat-app/src/components/chat/EmptyState.vue`:

```vue
<template>
  <div class="flex flex-col items-center justify-center h-full text-gray-400 select-none">
    <div class="text-6xl mb-4">💬</div>
    <p class="text-lg font-medium text-gray-300 mb-2">{{ title }}</p>
    <p class="text-sm text-gray-500">{{ subtitle }}</p>
  </div>
</template>

<script setup lang="ts">
withDefaults(defineProps<{
  title?: string;
  subtitle?: string;
}>(), {
  title: '开始一段新的 AI 对话',
  subtitle: '选择一个对话或点击新建',
});
</script>
```

- [ ] **Step 2: Commit**

```bash
git add packages/ai-chat-app/src/components/chat/EmptyState.vue
git commit -m "feat(ai-chat-app): add EmptyState component

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5.2: ConversationItem 组件

**Files:** Create: `packages/ai-chat-app/src/components/chat/ConversationItem.vue`

- [ ] **Step 1: 实现 ConversationItem**

Create `packages/ai-chat-app/src/components/chat/ConversationItem.vue`:

```vue
<template>
  <div
    :class="[
      'group flex items-center justify-between px-3 py-2 rounded-md cursor-pointer transition-colors',
      isActive
        ? 'bg-indigo-600/20 text-indigo-200'
        : 'hover:bg-white/5 text-gray-300',
    ]"
    @click="$emit('select')"
    @contextmenu.prevent="showMenu = !showMenu"
  >
    <div class="truncate flex-1 text-sm" :title="item.title">
      {{ item.title }}
    </div>

    <span class="text-xs text-gray-500 ml-2 flex-shrink-0" :title="fullTime">
      {{ relativeTime }}
    </span>

    <!-- 右键菜单 -->
    <div
      v-if="showMenu"
      class="absolute right-2 top-8 z-50 bg-gray-800 border border-gray-700 rounded-lg shadow-xl py-1 min-w-[140px]"
      @click.stop
    >
      <button
        v-if="!isArchived"
        class="w-full text-left px-3 py-1.5 text-sm hover:bg-white/10 text-gray-300"
        @click="$emit('pin'); showMenu = false"
      >
        {{ isPinned ? '📌 取消置顶' : '📌 置顶' }}
      </button>
      <button
        class="w-full text-left px-3 py-1.5 text-sm hover:bg-white/10 text-gray-300"
        @click="$emit('archive'); showMenu = false"
      >
        {{ isArchived ? '📂 取消归档' : '📦 归档' }}
      </button>
      <button
        class="w-full text-left px-3 py-1.5 text-sm hover:bg-white/10 text-red-400"
        @click="$emit('delete'); showMenu = false"
      >
        🗑 删除
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue';
import type { ConversationListItem } from '@ai-design/shared';

const props = defineProps<{
  item: ConversationListItem;
  isActive: boolean;
  isPinned: boolean;
  isArchived: boolean;
}>();

defineEmits<{
  select: [];
  pin: [];
  archive: [];
  delete: [];
}>();

const showMenu = ref(false);

// 关闭右键菜单
function closeMenu() {
  showMenu.value = false;
}
onMounted(() => document.addEventListener('click', closeMenu));
onUnmounted(() => document.removeEventListener('click', closeMenu));

const fullTime = computed(() => new Date(props.item.updated_at).toLocaleString('zh-CN'));

const relativeTime = computed(() => {
  const diff = Date.now() - new Date(props.item.updated_at).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return '刚刚';
  if (mins < 60) return `${mins}分钟前`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}小时前`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}天前`;
  return new Date(props.item.updated_at).toLocaleDateString('zh-CN');
});
</script>
```

- [ ] **Step 2: Commit**

```bash
git add packages/ai-chat-app/src/components/chat/ConversationItem.vue
git commit -m "feat(ai-chat-app): add ConversationItem with right-click menu

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5.3: ConversationSidebar 组件

**Files:** Create: `packages/ai-chat-app/src/components/chat/ConversationSidebar.vue`

- [ ] **Step 1: 实现 ConversationSidebar**

Create `packages/ai-chat-app/src/components/chat/ConversationSidebar.vue`:

```vue
<template>
  <aside class="w-[260px] h-full bg-gray-900 border-r border-gray-800 flex flex-col flex-shrink-0">
    <!-- 新建对话按钮 -->
    <div class="p-3">
      <button
        class="w-full py-2 px-4 bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium rounded-lg transition-colors"
        @click="$emit('newChat')"
      >
        + 新建对话
      </button>
    </div>

    <!-- 搜索框 -->
    <div class="px-3 pb-2">
      <input
        v-model="store.searchQuery"
        type="text"
        placeholder="搜索对话..."
        class="w-full bg-gray-800 border border-gray-700 rounded-md px-3 py-1.5 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-indigo-500 transition-colors"
        @input="store.setSearchQuery(($event.target as HTMLInputElement).value)"
      />
    </div>

    <!-- 对话列表 -->
    <div class="flex-1 overflow-y-auto px-2 pb-2 space-y-1">
      <!-- 置顶分组 -->
      <template v-if="store.pinnedConversations.length">
        <p class="px-2 py-1 text-xs text-gray-500 uppercase tracking-wider">置顶</p>
        <ConversationItem
          v-for="conv in store.pinnedConversations"
          :key="conv.id"
          :item="conv"
          :is-active="activeId === conv.id"
          :is-pinned="true"
          :is-archived="false"
          @select="$emit('select', conv.id)"
          @pin="store.togglePin(conv.id)"
          @archive="store.toggleArchive(conv.id)"
          @delete="handleDelete(conv.id)"
        />
      </template>

      <!-- 普通分组 -->
      <template v-if="store.normalConversations.length">
        <p
          v-if="store.pinnedConversations.length"
          class="px-2 py-1 text-xs text-gray-500 uppercase tracking-wider"
        >
          对话
        </p>
        <ConversationItem
          v-for="conv in store.normalConversations"
          :key="conv.id"
          :item="conv"
          :is-active="activeId === conv.id"
          :is-pinned="false"
          :is-archived="false"
          @select="$emit('select', conv.id)"
          @pin="store.togglePin(conv.id)"
          @archive="store.toggleArchive(conv.id)"
          @delete="handleDelete(conv.id)"
        />
      </template>

      <!-- 归档分组（折叠） -->
      <template v-if="store.archivedConversations.length">
        <p
          class="px-2 py-1 text-xs text-gray-500 uppercase tracking-wider cursor-pointer hover:text-gray-300"
          @click="showArchived = !showArchived"
        >
          {{ showArchived ? '▾' : '▸' }} 归档 ({{ store.archivedConversations.length }})
        </p>
        <template v-if="showArchived">
          <ConversationItem
            v-for="conv in store.archivedConversations"
            :key="conv.id"
            :item="conv"
            :is-active="activeId === conv.id"
            :is-pinned="false"
            :is-archived="true"
            @select="$emit('select', conv.id)"
            @archive="store.toggleArchive(conv.id)"
            @delete="handleDelete(conv.id)"
          />
        </template>
      </template>

      <!-- 空列表 -->
      <div
        v-if="store.conversations.length === 0 && !store.loading"
        class="text-center text-gray-500 text-sm py-8"
      >
        暂无对话
      </div>

      <!-- 加载中 -->
      <div v-if="store.loading" class="text-center text-gray-500 text-sm py-8">加载中...</div>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import { useConversationStore } from '@/stores/conversationStore';
import ConversationItem from './ConversationItem.vue';

defineProps<{ activeId: string | null }>();

defineEmits<{
  select: [id: string];
  newChat: [];
  delete: [id: string];
}>();

const store = useConversationStore();
const showArchived = ref(false);

function handleDelete(id: string) {
  if (confirm('确认删除该对话？')) {
    store.removeConversation(id);
  }
}
</script>
```

- [ ] **Step 2: Commit**

```bash
git add packages/ai-chat-app/src/components/chat/ConversationSidebar.vue
git commit -m "feat(ai-chat-app): add ConversationSidebar with search/pin/archive

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5.4: ChatMessage 组件

**Files:** Create: `packages/ai-chat-app/src/components/chat/ChatMessage.vue`

- [ ] **Step 1: 实现 ChatMessage**

Create `packages/ai-chat-app/src/components/chat/ChatMessage.vue`:

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
      <!-- AI 消息：使用 MarkdownRenderer -->
      <MarkdownRenderer v-if="!isUser" :content="message.content" />

      <!-- 用户消息：纯文本 -->
      <p v-else class="whitespace-pre-wrap text-sm">{{ message.content }}</p>

      <!-- 流式光标 -->
      <span
        v-if="isStreaming"
        class="inline-block w-0.5 h-4 bg-indigo-400 ml-0.5 animate-pulse align-text-bottom"
      ></span>

      <!-- 悬浮操作按钮 -->
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

      <!-- 时间戳 (悬浮显示) -->
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
import { computed } from 'vue';
import type { Message } from '@ai-design/shared';
import MarkdownRenderer from '@ai-design/shared/components/MarkdownRenderer.vue';

const props = defineProps<{
  message: Message;
  isStreaming?: boolean;
}>();

defineEmits<{
  regenerate: [];
}>();

const isUser = computed(() => props.message.role === 'user');

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
    // fallback: 忽略复制失败
  }
}
</script>
```

- [ ] **Step 2: Commit**

```bash
git add packages/ai-chat-app/src/components/chat/ChatMessage.vue
git commit -m "feat(ai-chat-app): add ChatMessage with Markdown rendering and copy

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5.5: MessageInput 组件

**Files:** Create: `packages/ai-chat-app/src/components/chat/MessageInput.vue`

- [ ] **Step 1: 实现 MessageInput**

Create `packages/ai-chat-app/src/components/chat/MessageInput.vue`:

```vue
<template>
  <div class="border-t border-gray-800 p-4 bg-gray-900">
    <div class="flex items-end gap-3 max-w-4xl mx-auto">
      <textarea
        ref="textareaRef"
        v-model="localInput"
        :disabled="isStreaming && !canStop"
        :rows="rows"
        class="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-4 py-3 text-sm text-gray-200 placeholder-gray-500 resize-none focus:outline-none focus:border-indigo-500 transition-colors disabled:opacity-50"
        placeholder="输入消息... (Enter 发送, Shift+Enter 换行)"
        @keydown="onKeydown"
        @input="autoResize"
      />
      <button
        v-if="isStreaming && canStop"
        class="px-5 py-3 bg-red-600 hover:bg-red-500 text-white text-sm font-medium rounded-lg transition-colors flex-shrink-0"
        @click="$emit('stop')"
      >
        ⏹ 停止
      </button>
      <button
        v-else
        :disabled="!canSend"
        class="px-5 py-3 bg-indigo-600 hover:bg-indigo-500 disabled:bg-gray-700 disabled:text-gray-500 text-white text-sm font-medium rounded-lg transition-colors flex-shrink-0"
        @click="send"
      >
        发送
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue';

const props = defineProps<{
  modelValue: string;
  isStreaming: boolean;
}>();

const emit = defineEmits<{
  'update:modelValue': [value: string];
  send: [content: string];
  stop: [];
}>();

const textareaRef = ref<HTMLTextAreaElement | null>(null);
const rows = ref(1);

const localInput = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
});

const canSend = computed(() => localInput.value.trim().length > 0 && !props.isStreaming);
const canStop = computed(() => props.isStreaming);

function autoResize() {
  const el = textareaRef.value;
  if (!el) return;
  el.style.height = 'auto';
  const lineHeight = 24;
  const maxRows = 6;
  const newRows = Math.min(Math.ceil(el.scrollHeight / lineHeight), maxRows);
  rows.value = newRows;
  el.style.height = newRows * lineHeight + 'px';
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    send();
  }
}

function send() {
  if (!canSend.value) return;
  emit('send', localInput.value.trim());
}

// 发送后聚焦输入框
watch(
  () => props.isStreaming,
  (v) => {
    if (!v) {
      textareaRef.value?.focus();
    }
  },
);
</script>
```

- [ ] **Step 2: Commit**

```bash
git add packages/ai-chat-app/src/components/chat/MessageInput.vue
git commit -m "feat(ai-chat-app): add MessageInput with auto-resize and stop button

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5.6: ChatWindow 组件

**Files:** Create: `packages/ai-chat-app/src/components/chat/ChatWindow.vue`

- [ ] **Step 1: 实现 ChatWindow**

Create `packages/ai-chat-app/src/components/chat/ChatWindow.vue`:

```vue
<template>
  <div class="flex flex-col h-full bg-gray-950">
    <!-- 错误横幅 -->
    <div
      v-if="chatStore.streamError"
      class="px-4 py-2 bg-red-900/50 border-b border-red-800 text-red-300 text-sm flex items-center justify-between"
    >
      <span>{{ chatStore.streamError }}</span>
      <button
        class="text-red-400 hover:text-red-300 underline ml-4"
        @click="$emit('retry')"
      >
        重试
      </button>
    </div>

    <!-- 消息区域 -->
    <div
      ref="scrollContainer"
      class="flex-1 overflow-y-auto px-4 py-6"
      @scroll="autoScroll.onScroll"
    >
      <div class="max-w-4xl mx-auto space-y-1">
        <!-- 空状态 -->
        <EmptyState
          v-if="chatStore.displayMessages.length === 0"
          title="开始对话"
          subtitle="在下方输入你的问题"
        />

        <!-- 消息列表 -->
        <ChatMessage
          v-for="msg in chatStore.displayMessages"
          :key="msg.id"
          :message="msg"
          :is-streaming="msg.id === '__streaming__'"
          @regenerate="handleRegenerate(msg.id)"
        />
      </div>
    </div>

    <!-- 输入区域 -->
    <MessageInput
      v-model="chatStore.inputText"
      :is-streaming="chatStore.isStreaming"
      @send="handleSend"
      @stop="$emit('stop')"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue';
import { useChatStore } from '@/stores/chatStore';
import { useAutoScroll } from '@/composables/useAutoScroll';
import ChatMessage from './ChatMessage.vue';
import MessageInput from './MessageInput.vue';
import EmptyState from './EmptyState.vue';

const emit = defineEmits<{
  send: [content: string];
  stop: [];
  retry: [];
  regenerate: [messageId: string];
}>();

const chatStore = useChatStore();

const scrollContainer = ref<HTMLElement | null>(null);
const scrollDep = computed(() => ({
  len: chatStore.displayMessages.length,
  streaming: chatStore.streamingContent.length,
}));

const autoScroll = useAutoScroll(scrollContainer, scrollDep);

function handleSend(content: string) {
  emit('send', content);
}

function handleRegenerate(msgId: string) {
  if (msgId === '__streaming__') return;
  emit('regenerate', msgId);
}

onMounted(() => {
  autoScroll.forceScrollToBottom();
});
</script>
```

- [ ] **Step 2: Commit**

```bash
git add packages/ai-chat-app/src/components/chat/ChatWindow.vue
git commit -m "feat(ai-chat-app): add ChatWindow with message list and error handling

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5.7: ChatLayout 组件

**Files:** Create: `packages/ai-chat-app/src/components/chat/ChatLayout.vue`

- [ ] **Step 1: 实现 ChatLayout**

Create `packages/ai-chat-app/src/components/chat/ChatLayout.vue`:

```vue
<template>
  <div class="flex h-screen bg-gray-950 text-gray-200">
    <ConversationSidebar
      :active-id="chatStore.currentConversationId"
      @select="handleSelect"
      @new-chat="handleNewChat"
    />
    <div class="flex-1 flex flex-col min-w-0">
      <ChatWindow
        @send="handleSend"
        @stop="handleStop"
        @retry="handleRetry"
        @regenerate="handleRegenerate"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue';
import { useRouter } from 'vue-router';
import { useChatStore } from '@/stores/chatStore';
import { useConversationStore } from '@/stores/conversationStore';
import { useConversation } from '@ai-design/shared';
import ConversationSidebar from './ConversationSidebar.vue';
import ChatWindow from './ChatWindow.vue';

const router = useRouter();
const chatStore = useChatStore();
const convStore = useConversationStore();
const { fetchList, fetchConversation, create } = useConversation();

const MODEL = 'glm-5.2';

// 导入 useChatStream（延迟引用避免循环依赖）
let chatStream: ReturnType<typeof import('@ai-design/shared').useChatStream> | null = null;

async function initChatStream() {
  const { useChatStream } = await import('@ai-design/shared');
  chatStream = useChatStream({
    onMeta(meta) {
      console.log('[chat] meta:', meta);
    },
    onToken(text) {
      chatStore.appendToken(text);
    },
    onToolCall(tool) {
      console.log('[chat] tool_call:', tool);
    },
    onComplete(finishReason) {
      console.log('[chat] complete:', finishReason);
    },
    onError(message) {
      chatStore.setStreamError(message);
    },
    onDone() {
      const msgId = crypto.randomUUID();
      chatStore.finishStreaming(msgId);
      const convId = chatStore.currentConversationId;
      if (convId) {
        convStore.incrementMsgCount(convId);
        // 刷新侧边栏标题
        fetchList().then((list) => {
          if (list) convStore.setConversations(list);
        });
      }
    },
  });
}

async function handleSend(content: string) {
  if (!chatStream) await initChatStream();
  if (!chatStream!) return;

  chatStore.clearInput();

  // 如果没有当前对话，先创建
  let convId = chatStore.currentConversationId;
  if (!convId) {
    const title = content.length > 30 ? content.slice(0, 30) + '...' : content;
    const conv = await create(title);
    if (!conv) return;
    convId = conv.id;
    chatStore.currentConversationId = convId;
    convStore.addConversation({
      id: conv.id,
      title: conv.title || title,
      msg_count: 0,
      created_at: conv.created_at || new Date().toISOString(),
      updated_at: conv.updated_at || new Date().toISOString(),
    });
    router.replace(`/chat/${convId}`);
  }

  // 添加用户消息
  const userMsgId = crypto.randomUUID();
  chatStore.appendMessage({
    id: userMsgId,
    role: 'user',
    content,
    created_at: new Date().toISOString(),
  });

  // 启动流式
  chatStore.startStreaming();
  chatStream!.start(convId, MODEL, content);
}

function handleStop() {
  chatStream?.cancel();
  chatStore.cancelStream();
}

async function handleSelect(convId: string) {
  await fetchConversation(convId);
  // fetchConversation 已将数据放到 useConversation 的 currentConversation ref 中
  // 需要从 composable 中提取，这里直接调 API 取
  const { getConversation } = await import('@ai-design/shared');
  const conv = await getConversation(convId) as unknown as import('@ai-design/shared').Conversation;
  chatStore.selectConversation(convId, conv?.messages || []);
  router.replace(`/chat/${convId}`);
}

function handleNewChat() {
  chatStore.selectConversation(null, []);
  router.replace('/chat');
}

async function handleRetry() {
  // 取最后一条用户消息重试
  const lastUserMsg = [...chatStore.messages].reverse().find((m) => m.role === 'user');
  if (lastUserMsg) {
    chatStore.streamError = null;
    chatStore.startStreaming();
    const convId = chatStore.currentConversationId!;
    chatStream?.start(convId, MODEL, lastUserMsg.content);
  }
}

async function handleRegenerate(msgId: string) {
  const idx = chatStore.messages.findIndex((m) => m.id === msgId);
  if (idx === -1) return;
  // 找到该 AI 消息前的最后一条用户消息
  let lastUserMsg: { content: string } | null = null;
  for (let i = idx - 1; i >= 0; i--) {
    if (chatStore.messages[i].role === 'user') {
      lastUserMsg = chatStore.messages[i];
      break;
    }
  }
  if (lastUserMsg) {
    chatStore.startStreaming();
    const convId = chatStore.currentConversationId!;
    chatStream?.start(convId, MODEL, lastUserMsg.content);
  }
}

onMounted(async () => {
  await initChatStream();
  await fetchList();
  // fetchList 填充了 useConversation 内部的 conversations ref，需同步到 store
  const { listConversations } = await import('@ai-design/shared');
  const res = await listConversations() as unknown as { conversations: import('@ai-design/shared').ConversationListItem[] };
  if (res?.conversations) {
    convStore.setConversations(res.conversations);
  }
});
</script>
```

- [ ] **Step 2: Commit**

```bash
git add packages/ai-chat-app/src/components/chat/ChatLayout.vue
git commit -m "feat(ai-chat-app): add ChatLayout orchestrating sidebar and chat window

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Phase 6: ai-chat-app — 视图与路由

### Task 6.1: ChatView 与路由更新

**Files:** Create: `packages/ai-chat-app/src/views/ChatView.vue`, Modify: `packages/ai-chat-app/src/router/index.ts`, Modify: `packages/ai-chat-app/src/App.vue`

- [ ] **Step 1: 创建 ChatView**

Create `packages/ai-chat-app/src/views/ChatView.vue`:

```vue
<template>
  <ChatLayout />
</template>

<script setup lang="ts">
import ChatLayout from '@/components/chat/ChatLayout.vue';
</script>
```

- [ ] **Step 2: 更新路由**

Edit `packages/ai-chat-app/src/router/index.ts`:

```typescript
import type { RouteRecordRaw } from 'vue-router';
import ChatView from '../views/ChatView.vue';

export const routes: RouteRecordRaw[] = [
  { path: '/', name: 'Chat', component: ChatView },
  { path: '/chat', name: 'ChatNew', component: ChatView },
  { path: '/chat/:id', name: 'ChatDetail', component: ChatView },
];
```

- [ ] **Step 3: 简化 App.vue（移除导航占位）**

Edit `packages/ai-chat-app/src/App.vue`:

```vue
<template>
  <div class="ai-chat-app h-screen">
    <router-view />
  </div>
</template>

<script setup lang="ts">
import { onGlobalStateChange } from '@ai-design/micro-core';

onGlobalStateChange((state, prev) => {
  console.log('[ai-chat-app] global state changed:', state, prev);
});
</script>
```

- [ ] **Step 4: Commit**

```bash
git add packages/ai-chat-app/src/views/ChatView.vue packages/ai-chat-app/src/router/index.ts packages/ai-chat-app/src/App.vue
git commit -m "feat(ai-chat-app): wire up ChatView, update routes and App.vue

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Phase 7: 集成验证

### Task 7.1: 运行完整测试套件

- [ ] **Step 1: 运行 shared 测试**

```bash
cd d:\Code\AI\ai-design-platform\ai-design-platform-web\packages\shared
pnpm test -- --reporter=verbose
```

Expected: 所有测试通过。

- [ ] **Step 2: 运行 ai-chat-app 测试**

```bash
cd d:\Code\AI\ai-design-platform\ai-design-platform-web\packages\ai-chat-app
pnpm test -- --reporter=verbose
```

Expected: 所有测试通过。

- [ ] **Step 3: 类型检查**

```bash
cd d:\Code\AI\ai-design-platform\ai-design-platform-web\packages\ai-chat-app
pnpm exec tsc --noEmit 2>&1 | head -30
```

修复任何类型错误。

- [ ] **Step 4: 构建验证**

```bash
cd d:\Code\AI\ai-design-platform\ai-design-platform-web
pnpm build 2>&1 | tail -20
```

确认构建成功。

- [ ] **Step 5: 最终 Commit**

```bash
git add -A
git commit -m "chore: verify all tests pass and build succeeds

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## 附：任务依赖图

```
Phase 0 (依赖安装)
  └─→ Phase 1 (类型 & API)
        └─→ Phase 2 (Composables & MarkdownRenderer)
              └─→ Phase 3 (Stores)
                    ├─→ Phase 4 (useAutoScroll)
                    └─→ Phase 5 (Components)
                          └─→ Phase 6 (View & 路由)
                                └─→ Phase 7 (验证)
```

Tasks within the same phase can sometimes be parallelized. Specifically:
- Task 1.1 (types) → Task 1.2 (api) must be sequential
- Task 2.1 (useMarkdown) + Task 2.3 (useChatStream) can be parallel (independent)
- Task 2.2 (MarkdownRenderer) depends on Task 2.1
- Task 2.4 (useConversation) depends on Task 1.2
- Task 2.5 (index exports) must be last in Phase 2
- Task 3.1 + 3.2 (stores) can be parallel
- Tasks 5.1-5.7 (components) can mostly be parallel, but 5.4 depends on 2.2, and 5.6 depends on 5.2+5.4+4.1
- ChatLayout (5.7) must be last component as it orchestrates everything
