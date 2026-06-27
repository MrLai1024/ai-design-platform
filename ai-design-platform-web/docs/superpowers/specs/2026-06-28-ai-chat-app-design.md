# AI Chat App 功能设计文档

> 版本: v1.0 | 日期: 2026-06-28 | 状态: 待实现

## 1. 概述

在 `ai-chat-app` 子应用中实现完整的 AI 对话功能，后端已有 Go Gateway + Python AI Service（GLM-5.2），前端通过 HTTP REST + SSE 流式对接。

**核心功能：**

1. **创建新对话** — 点击新建进入空白聊天，首次发送消息后自动创建对话
2. **历史对话记录** — 左侧边栏展示，支持搜索/置顶/归档/删除
3. **AI 对话窗口流式输出** — SSE 逐字渲染，Markdown + 代码高亮，支持取消/重新生成

**约束：** 不影响其他子应用，公共模块适当提取到 `@ai-design/shared`

---

## 2. 架构设计

### 2.1 整体架构

```
ai-chat-app (Vue 3 + Pinia)
  ├── stores/          ← 应用级状态（对话列表、聊天状态）
  ├── components/      ← UI 组件
  ├── composables/     ← useAutoScroll (应用专属)
  └── views/           ← ChatView

@ai-design/shared ← 提取的公共模块
  ├── types/chat.ts        ← 类型定义
  ├── api/chat.ts          ← API 封装
  ├── composables/         ← useChatStream / useConversation / useMarkdown
  └── components/          ← MarkdownRenderer

后端 (Go Gateway + Python AI Service)
  GET/POST/DELETE  /api/v1/conversations
  POST             /api/v1/conversations/:id/messages  (SSE)
  POST             /api/v1/chat/cancel/:generation_id
```

### 2.2 选择方案

**组合式分层架构（方案 2）** — Vue 3 Composables 为逻辑单元，Pinia Store 只管应用状态，公共逻辑提取到 shared。

理由：
- 职责清晰，Composable 可独立测试和复用
- 对齐项目已有的 Vue 3 + Pinia 范式
- SSE 抽象层方便后续 `ai-generation-app` 等子应用复用
- 不引入重型聊天 UI 框架（体积大、与 Tailwind 冲突、流式定制受限）

---

## 3. 文件结构

### 3.1 `@ai-design/shared` 新增

```
src/
├── types/
│   └── chat.ts              ← 新增
├── api/
│   └── chat.ts              ← 新增
├── composables/
│   ├── useChatStream.ts     ← 新增
│   ├── useConversation.ts   ← 新增
│   └── useMarkdown.ts       ← 新增
└── components/
    └── MarkdownRenderer.vue ← 新增
```

### 3.2 `ai-chat-app` 新增

```
src/
├── types/
│   └── chat.ts                    ← 后端定义的类型（仅应用内扩展类型放此）
├── composables/
│   └── useAutoScroll.ts           ← 新增
├── stores/
│   ├── conversationStore.ts       ← 新增
│   └── chatStore.ts               ← 新增
├── components/
│   └── chat/
│       ├── ChatLayout.vue         ← 新增
│       ├── ConversationSidebar.vue ← 新增
│       ├── ConversationItem.vue   ← 新增
│       ├── ChatWindow.vue         ← 新增
│       ├── ChatMessage.vue        ← 新增
│       ├── MessageInput.vue       ← 新增
│       └── EmptyState.vue         ← 新增
├── views/
│   └── ChatView.vue               ← 新增（替代 Home.vue）
└── router/
    └── index.ts                   ← 更新
```

---

## 4. 类型定义 (`@ai-design/shared/src/types/chat.ts`)

对齐后端 Go 结构体字段（已验证 [conversation.go](d:\Code\AI\ai-design-platform\ai-design-platform-server\gateway\internal\store\conversation.go) 和 [handler/conversation.go](d:\Code\AI\ai-design-platform\ai-design-platform-server\gateway\internal\handler\conversation.go)）：

```typescript
interface ConversationListItem {
  id: string
  title: string
  msg_count: number
  created_at: string
  updated_at: string
}

interface Message {
  id: string
  role: 'system' | 'user' | 'assistant'
  content: string
  created_at: string
}

interface Conversation {
  id: string
  title: string
  messages: Message[]
  created_at: string
  updated_at: string
}

// SSE 事件类型
type StreamEventType = 'meta' | 'token' | 'tool_call' | 'complete' | 'error' | 'done'

interface TokenEvent {
  text: string       // 后端字段名是 text
  index: number
}

interface CompleteEvent {
  finish_reason: string  // data 是 JSON 字符串，需二次 parse
}

interface ToolCallEvent {
  id: string
  name: string
  arguments: string
}

interface MetaEvent {
  generation_id: string
  conversation_id?: string
  message_id?: string
}

interface ErrorEvent {
  message: string
  code?: string
}

interface SendMessageRequest {
  model: string     // 必填 (binding:"required")，传 "glm-5.2"
  content: string   // 必填
}

interface ListConversationsResponse {
  conversations: ConversationListItem[]  // 后端用 conversations 键包裹
}
```

---

## 5. API 封装 (`@ai-design/shared/src/api/chat.ts`)

基于已有的 `http` 实例（baseURL: `/api`，超时 15s，Bearer 令牌拦截器）：

```typescript
// CRUD
createConversation(title: string) → POST /v1/conversations  body: { title }
listConversations()              → GET  /v1/conversations   响应: { conversations: [...] }
getConversation(id)              → GET  /v1/conversations/:id
deleteConversation(id)           → DEL  /v1/conversations/:id

// SSE 流式（原生 fetch，不用 Axios 以支持 ReadableStream）
streamChat(conversationId, model, content) →
  fetch POST /api/v1/conversations/:id/messages
  body: { model, content }
  返回: Response (由 useChatStream 消费 body.getReader())

// 取消
cancelGeneration(generationId)  → POST /api/v1/chat/cancel/:generation_id
```

---

## 6. 数据流与状态管理

### 6.1 Pinia Store

#### conversationStore（ai-chat-app 内）

| 字段 | 类型 | 说明 |
|------|------|------|
| conversations | `ConversationListItem[]` | 对话列表 |
| searchQuery | `string` | 搜索词 |
| activeFilter | `'all' \| 'pinned' \| 'archived'` | 过滤器 |
| loading | `boolean` | 加载状态 |
| **getter** `filteredConversations` | | 搜索 + 过滤组合 |
| **getter** `pinnedConversations` | | 置顶分组 |
| **getter** `normalConversations` | | 普通分组 |
| `fetchList()` | | 初始化/刷新 |
| `createConversation(title)` | | 创建（乐观更新） |
| `deleteConversation(id)` | | 删除（乐观移除） |
| `togglePin(id)` / `toggleArchive(id)` | | 切换置顶/归档（本地状态） |
| `setSearchQuery(q)` | | 搜索词（本地过滤） |

#### chatStore（ai-chat-app 内）

| 字段 | 类型 | 说明 |
|------|------|------|
| currentConversationId | `string \| null` | 当前对话 |
| messages | `Message[]` | 历史消息 |
| streamingContent | `string` | SSE 流式累加内容 |
| isStreaming | `boolean` | 是否流式输出中 |
| streamError | `string \| null` | 流式错误 |
| inputText | `string` | 输入框内容 |
| **getter** `displayMessages` | | messages + 未完成流式消息 |
| `selectConversation(id)` | | 切换对话，加载历史 |
| `sendMessage(text)` | | 发送 → 启动 SSE |
| `cancelStream()` | | 中止流式 |
| `regenerate(msgId)` | | 重新生成回复 |
| `clearInput()` | | 清空输入 |

### 6.2 Composable

| Composable | 位置 | 职责 |
|-----------|------|------|
| `useChatStream` | shared | SSE ReadableStream 读取 → 解析帧 → 分发 token/error/done 事件 → 内置重连(2次) → cancel 调用 |
| `useConversation` | shared | 包装 API CRUD 方法 → 统一 `{ data, error }` 返回 |
| `useMarkdown` | shared | `marked` 解析 + `highlight.js` 着色 → 流式防抖(16ms) → 不完整 Markdown 容错 |
| `useAutoScroll` | chat-app | 自动滚底 → 检测手动上滚暂停 → 滚回底部恢复 → 切换对话强制滚底 |

### 6.3 典型交互流

```
用户点击"新建对话"
  → 路由到 /chat，输入框获得焦点

用户输入消息，按发送
  → chatStore.sendMessage(text)
  → conversationStore.createConversation(text前30字作为标题)
  → useChatStream.start(conversationId, model, content)
  → SSE token → chatStore.streamingContent 累加
  → useMarkdown 实时渲染 → MarkdownRenderer 更新
  → useAutoScroll 自动滚底
  → event:done → 流式内容固化为 messages 末尾消息
  → conversationStore.fetchList() 刷新侧边栏

用户切换对话
  → chatStore.selectConversation(id)
  → 若正在流式，先 cancelStream()
  → 加载历史消息 → 滚底

用户搜索
  → conversationStore.setSearchQuery("登录")
  → filteredConversations getter 实时过滤侧边栏
```

---

## 7. 组件设计

### 7.1 组件树

```
ChatView.vue
└── ChatLayout.vue (flex-row, h-screen)
    ├── ConversationSidebar.vue (w-260px, flex-shrink-0)
    │   ├── 新建对话按钮
    │   ├── 搜索框（实时本地过滤，高亮匹配文字）
    │   ├── 置顶分组
    │   │   └── ConversationItem.vue × N
    │   ├── 普通分组  
    │   │   └── ConversationItem.vue × N
    │   └── 归档分组（折叠）
    │       └── ConversationItem.vue × N
    └── ChatWindow.vue (flex-1)
        ├── 对话标题栏
        ├── 消息列表区 (flex-1, overflow-y)
        │   ├── ChatMessage.vue × N（历史）
        │   ├── ChatMessage.vue（流式中，闪烁光标）
        │   └── 滚动锚点
        ├── ErrorBanner（条件显示）
        └── MessageInput.vue
            ├── Textarea（自适应 1-6 行）
            ├── 停止按钮（isStreaming 时）
            └── 发送按钮（非 streaming 时）
```

### 7.2 各状态视图

| 场景 | 左侧栏 | 右侧主区域 |
|------|--------|-----------|
| 首次加载（无对话） | 空列表 + 新建引导 | EmptyState: "开始一段新的AI对话" |
| 有对话未选中 | 列表正常显示 | EmptyState: "选择左侧对话或新建" |
| 对话中 | 当前对话高亮 | 消息列表 + 输入框 |
| 流式输出中 | 不变 | 消息逐字出现，滚动跟随，发送→停止 |
| 网络错误 | 静默，可下拉刷新 | 顶部 error banner + 重试 |
| 加载中 | 骨架屏 | 骨架屏 |

### 7.3 关键交互

- **输入**：Enter 发送 / Shift+Enter 换行 / 空内容禁用发送 / 流式中发送变红色停止
- **消息**：hover 显示操作按钮（复制/重新生成/编辑），代码块显示语言标签+复制按钮
- **右键菜单**：对话列表项右键 → 置顶/归档/删除（需确认）
- **搜索**：侧边栏顶部输入框，实时本地过滤，匹配文字高亮
- **滚动**：流式自动滚底，用户上滚>80px 暂停，滚回底部恢复

---

## 8. SSE 解析规范

### 8.1 连接参数

- Content-Type: `text/event-stream`
- Cache-Control: `no-cache`
- Connection: `keep-alive`

### 8.2 事件帧格式

```
event: meta
data: {"generation_id":"...","conversation_id":"...","message_id":"..."}

event: token  
data: {"text":"你好","index":0}

event: tool_call
data: {"id":"...","name":"search","arguments":"{...}"}

event: complete
data: {"finish_reason":"stop"}         ← data 是 JSON 字符串

event: error
data: {"code":"MODEL_TIMEOUT","message":"模型超时"}

event: done
data: [DONE]
```

### 8.3 解析流程

1. `fetch` → `response.body.getReader()` 逐 chunk 读取
2. `TextDecoder` 解码字节 → 按 `\n\n` 切分事件
3. 逐帧解析 `event` / `data` 字段
4. `token` → 追加 `text` 到 `streamingContent`
5. `complete` → 停止流，用 `finish_reason` 做收尾
6. `error` → 设置 `streamError`，保留已收到内容
7. `done` → 关闭流，将流式内容固化为消息

---

## 9. 错误处理

| 场景 | 处理 |
|------|------|
| 网络断开 | 显示 "网络连接中断，点击重试"，已收到内容保留 |
| AI 服务不可用 (503) | banner "AI 服务暂时不可用"，30s 自动重试 |
| SSE error 事件 | 已输出内容保留，末尾追加红色 `[生成中断: ...]` |
| 对话不存在 (404) | toast "对话已被删除"，自动跳回空状态 |
| 请求超时 | Axios 15s 超时后显示提示，输入内容不丢失 |
| Markdown 异常 | try-catch 降级显示纯文本，不白屏 |
| 空内容发送 | 前端拦截，按钮 disabled |
| 重复发送 | isStreaming 期间不允许 |
| 流式中切换对话 | 先 cancelStream() 再切换 |
| 用户主动停止 | 调 POST /api/v1/chat/cancel/:generation_id，已输出保留 |

---

## 10. 测试策略

### 10.1 单元测试

| 模块 | 关键用例 |
|------|---------|
| `useChatStream` | SSE 帧解析（6 种事件类型）、取消逻辑、重连、异常帧容错 |
| `useConversation` | CRUD 对应 API 方法、数据格式验证、错误传播 |
| `useMarkdown` | 标准 Markdown、代码高亮、不完整 Markdown 容错、XSS 防护 |
| `conversationStore` | 筛选 getter、搜索过滤、乐观更新 |
| `chatStore` | 消息追加、流式累加、切换重置 |
| `api/chat.ts` | 请求体格式对齐后端、URL 拼接 |

### 10.2 组件测试

| 组件 | 关键场景 |
|------|---------|
| `ConversationSidebar` | 列表渲染、搜索过滤、分组排序、空状态 |
| `ChatMessage` | 用户/AI 样式、Markdown 渲染、hover 按钮、时间戳 |
| `MessageInput` | Enter 发送、Shift+Enter 换行、空禁用、停止按钮 |
| `ChatWindow` | 消息滚动、空状态、error banner |

### 10.3 集成测试

- 完整对话流程：创建 → 发送 → SSE 接收 → 消息更新 → 侧边栏刷新
- 切换对话：流式中切换 → 流取消 → 历史加载
- 错误恢复：断网 → 错误提示 → 重试 → 成功

---

## 11. 依赖

### 11.1 现有依赖（无需新增）

- Vue 3.4 + Pinia 2.1 + Vue Router 4.2
- Tailwind CSS v3
- `@ai-design/shared`（Axios `http` 实例）
- TypeScript、Webpack 5

### 11.2 需新增

| 包 | 用途 |
|---|------|
| `marked` | Markdown 解析（轻量，~20KB） |
| `highlight.js` | 代码语法高亮（按需加载语言包） |

---

## 12. 路由

```
/              → ChatView (EmptyState)
/chat          → ChatView (新建，无选中对话)
/chat/:id      → ChatView (加载指定对话)
```

替代现有 `Home.vue` 和 `About.vue` 的路由占位。

---

## 13. 不纳入范围

- 后端持久化（PostgreSQL）— 后续 Phase 2
- 认证鉴权（JWT）— 后续 Phase 2
- 多用户隔离 — 后续 Phase 2
- Agent/工具调用可视化 — 后续 Phase 2
- 国际化 i18n — 后续按需
- 文件上传/图片生成 — 不在 chat-app 范围
