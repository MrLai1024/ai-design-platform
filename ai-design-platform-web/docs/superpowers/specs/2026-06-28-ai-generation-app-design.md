# AI Generation App 设计文档

**日期**: 2026-06-28
**状态**: 已确认
**参考**: AI2WEB (WebAppDesign/AI2WEB)

## 1. 概述

在 `ai-generation-app` 微应用中实现 AI 对话 → 流式生成代码 → 浏览器端编译 → 沙箱实时渲染的完整流水线。用户通过自然语言描述需求，AI 流式生成 Vue SFC 代码，前端自动解析、编译并在 iframe 沙箱中实时预览。

## 2. 核心决策

| 决策项 | 选择 | 理由 |
|--------|------|------|
| 交互模式 | 聊天 + 代码生成混合 | 对话中的代码块自动编译渲染，非代码内容正常展示 |
| 编译渲染 | 前端编译 `@vue/repl` + `@babel/standalone`，iframe sandbox | AI2WEB 已验证可行，零服务端成本，即时生效 |
| 组件库 | 多组件库可选：Tailwind / Ant Design Vue / Element Plus / ECharts | 用户在输入区选择，文档注入到 system prompt |
| 对话管理 | 单会话模式，刷新即清空 | 最小化后端依赖，数据由 Pinia store 承载 |
| 文件支持 | 多文件生成 + 可编辑 + tab 切换 | 完整支持复杂项目，用户可手动修改任何文件 |
| 后端 | 复用 ai-design-platform-server（Go + Python），无需改动 | 现有 SSE streaming API 完全满足需求 |
| 架构模式 | Composable 驱动（方案 B） | 关注点分离，可独立测试，符合 Vue 3 习惯用法 |

## 3. 整体架构

```
┌──────────────────────────────────────────────────────────┐
│  views/GenerationView.vue  (三栏布局壳)                    │
│                                                          │
│  ┌─────────────┐  ┌──────────────────┐  ┌──────────────┐ │
│  │ ChatPanel   │  │ CodeEditor       │  │ PreviewFrame │ │
│  │             │  │ ┌──────────────┐ │  │              │ │
│  │ 消息流      │  │ │ Tab: File1   │ │  │ iframe       │ │
│  │ - 用户消息  │  │ │ Tab: File2   │ │  │ sandbox      │ │
│  │ - AI 回复   │  │ ├──────────────┤ │  │              │ │
│  │ - 代码卡片  │  │ │ Monaco       │ │  │ 实时渲染     │ │
│  │             │  │ │ 代码编辑区   │ │  │              │ │
│  │ 输入框      │  │ └──────────────┘ │  │              │ │
│  │ - 组件库选择│  │                  │  │              │ │
│  └─────────────┘  └──────────────────┘  └──────────────┘ │
└──────────────────────────────────────────────────────────┘
```

## 4. 数据流管道

```
用户输入 "用表格展示用户列表"
        │
        ▼
┌─────────────────────────────────────────────┐
│  useStreamChat.send(message, lib)            │
│  - 构建 system prompt（含组件文档注入）       │
│  - POST /api/v1/chat/stream (SSE)           │
│  - 逐 token 追加到 store.messages            │
└──────────────────────┬──────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────┐
│  useCodeParser                              │
│  - 实时检测 markdown 代码块边界              │
│  - 解析多文件结构 (## FileName.vue)          │
│  - 更新 store.files, 标记 dirtyFiles        │
└──────────────────────┬──────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────┐
│  useMultiCompiler (防抖 300ms)              │
│  - 编译 dirtyFiles 中的每个 SFC              │
│  - 使用 @vue/repl + @babel/standalone       │
│  - 合并编译结果 → store.compiledOutput      │
└──────────────────────┬──────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────┐
│  usePreviewRenderer                        │
│  - 安全扫描编译产物                          │
│  - 构建完整 HTML（注入组件库 CDN）           │
│  - 写入 iframe.srcdoc                       │
│  - 错误捕获回显                             │
└─────────────────────────────────────────────┘
```

## 5. 视图层

### 5.1 GenerationView.vue — 三栏布局

- 默认比例 30% / 35% / 35%，面板可拖拽调整
- 窄屏 (< 1024px)：聊天全宽，代码和预览纵向堆叠
- 移动端 (< 768px)：标签页切换三栏

### 5.2 ChatPanel.vue — 聊天面板（左侧）

- 消息列表：用户消息气泡（右对齐）+ AI 消息气泡（左对齐）
- AI 消息中非代码文本渲染为 Markdown
- 检测到代码块时，渲染特殊的"代码生成卡片"（文件列表 + 预览入口）
- 底部 ChatInput：textarea + 组件库选择器 + 发送/取消按钮

### 5.3 CodeEditor.vue — 代码编辑器（中间）

- 顶部 TabBar：多文件 tab 切换，支持关闭
- 每个 tab 显示文件名 + dirty 指示器 + 关闭按钮
- "+" 按钮新建文件
- Monaco Editor 主体：语法高亮、Vue/TS 自动补全
- 编辑自动触发 debounced 编译（500ms）或 Cmd/Ctrl+S 即时触发

### 5.4 PreviewFrame.vue — 预览面板（右侧）

- 工具栏：刷新按钮、错误计数 badge、全屏按钮
- iframe sandbox 渲染（`allow-scripts` + `srcdoc`）
- 底部可折叠的编译错误面板

## 6. Composable 设计

### 6.1 useStreamChat

```typescript
export function useStreamChat() {
  const store = useGenerationStore()
  async function send(content: string, lib: ComponentLibrary): Promise<void>
  function cancel(): void
  return { send, cancel, isStreaming }
}
```

- 调用 `POST /api/v1/chat/stream`，`ReadableStream` 读取 SSE
- 处理三种事件：`token`（追加）、`complete`（完成）、`error`（报错）
- `AbortController` 支持取消

### 6.2 useCodeParser

```typescript
export function useCodeParser() {
  function parseCodeBlocks(markdown: string): ParsedCodeBlock[]
  function updateFiles(blocks: ParsedCodeBlock[]): void
  return { parseCodeBlocks }
}
```

- 监听 `store.lastAssistantMessage.content` 变化
- 正则匹配多文件标记 `## FileName.vue` + ` ```vue ` 代码块
- 无标记时回退为单文件模式（默认 App.vue）
- 内容相同时不触发更新（消重）

### 6.3 useMultiCompiler

```typescript
export function useMultiCompiler() {
  async function compile(): Promise<void>
  return { compile, compileError }
}
```

- 防抖 300ms 监听 `store.dirtyFiles`
- 逐文件调用 `@vue/repl` 的 SFC 编译器
- 编译失败时设置 `store.compileError` 并停止后续编译
- 成功清空 `dirtyFiles`

### 6.4 usePreviewRenderer

```typescript
export function usePreviewRenderer() {
  function renderToIframe(compiledCode: string): void
  function handleIframeError(event: MessageEvent): void
  return { iframeRef, renderToIframe }
}
```

- 监听 `store.compiledOutput` 变化
- 安全扫描：拦截 `document.cookie`、`localStorage`、`eval`、`Function()` 等
- 构建完整 HTML 文档：注入组件库 CDN + Tailwind CDN + 错误边界
- 通过 `srcdoc` 写入 iframe
- `window.onerror` → `postMessage` 回传给父窗口展示

### 6.5 useComponentDocs

```typescript
export function useComponentDocs() {
  function getSystemPrompt(): string    // base + lib doc + output format
  function getCdnUrls(): string[]       // 组件库 CDN URLs
  return { currentLib, getSystemPrompt, getCdnUrls, libraryConfigs }
}
```

支持的组件库配置：

```typescript
type ComponentLibrary = 'tailwind' | 'antd' | 'element' | 'echarts'

// 每个库配置：cdnUrls（iframe 注入）+ docInjection（system prompt 注入）
```

## 7. 状态管理

### Pinia Store (`stores/generation.ts`)

```typescript
interface GenerationState {
  messages: Message[]           // 对话历史
  files: Map<string, FileEntry> // 当前生成的文件
  activeFile: string | null     // 当前编辑的文件名
  isStreaming: boolean          // 是否正在接收 SSE
  compiledOutput: string        // 编译后的 HTML
  compileError: string | null   // 编译错误信息
}

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string               // 原始 markdown
  codeBlocks: ParsedCodeBlock[] // 解析出的代码块
  timestamp: number
  isStreaming: boolean
}

interface FileEntry {
  filename: string
  content: string
  language: 'vue' | 'typescript' | 'javascript' | 'css'
  isDirty: boolean
  source: 'ai' | 'user'
}
```

Store 是唯一的状态汇合点，composables 通过 store 通信，组件只消费 store + 调用 composable 方法。

## 8. 目录结构

```
ai-generation-app/src/
├── views/
│   └── GenerationView.vue          # 三栏布局主视图
├── components/
│   ├── ChatPanel.vue               # 聊天面板
│   ├── ChatInput.vue               # 输入框 + 组件库选择
│   ├── CodeEditor.vue              # 代码编辑器 (Monaco)
│   ├── PreviewFrame.vue            # iframe 预览 + 错误面板
│   └── FileTabBar.vue              # 文件 tab 切换栏
├── composables/
│   ├── useStreamChat.ts            # SSE 流式聊天
│   ├── useCodeParser.ts            # 代码块解析 + 多文件分离
│   ├── useMultiCompiler.ts         # @vue/repl 多文件编译
│   ├── usePreviewRenderer.ts       # iframe 沙箱渲染 + 安全扫描
│   └── useComponentDocs.ts         # 组件库文档注入
├── stores/
│   └── generation.ts               # Pinia store (唯一状态汇合点)
├── utils/
│   ├── compileSFC.ts               # @vue/repl 单文件编译封装
│   ├── parseMultiSFC.ts            # 多文件 markdown 解析
│   ├── securityScan.ts             # 代码安全扫描
│   └── buildPreviewHtml.ts         # 构建 iframe srcdoc HTML
├── types/
│   └── generation.ts               # 所有 TypeScript 类型定义
├── router/
│   └── index.ts                    # 路由：/ → GenerationView
└── styles/
    └── generation.css              # 三栏布局 + Monaco 覆写样式
```

## 9. 新增依赖

```json
{
  "@vue/repl": "^4.x",
  "@babel/standalone": "^7.x",
  "monaco-editor": "^0.50.x",
  "markdown-it": "^14.x"
}
```

Webpack 需配置 `MonacoWebpackPlugin` 按需加载 Vue/TS 语言支持。

## 10. 后端

**无需改动。** 现有 API 完全满足需求：

| 现有接口 | 用途 |
|----------|------|
| `POST /api/v1/chat/stream` | SSE 流式聊天（system prompt 由前端构建） |
| `POST /api/v1/chat/cancel/:id` | 取消生成 |

前端在请求 body 中直接传入包含组件文档的完整 `messages` 数组，后端透传给 LLM。

需确认：gateway CORS 配置允许 `ai-generation-app` 的源。

## 11. 安全设计

### iframe 沙箱
- `sandbox="allow-scripts"`（不设置 `allow-same-origin`，防止访问父窗口）
- 代码安全扫描在编译产物写入 `srcdoc` 前执行
- 拦截规则：
  - `document.cookie`
  - `localStorage` / `sessionStorage`
  - `fetch()` / `XMLHttpRequest` 向外部域请求
  - `eval()` / `new Function()`
  - `window.top` / `window.parent` 访问

### 代码注入防护
- 用户手动编辑的代码同样经过安全扫描后才编译渲染
- 编译失败时显示错误但不暴露编译工具链细节

## 12. 测试策略

| 层级 | 测试内容 | 工具 |
|------|---------|------|
| utils | `parseMultiSFC` 解析准确性、`securityScan` 拦截有效性、`compileSFC` 编译正确性 | Vitest |
| composables | Mock SSE ReadableStream 测试 `useStreamChat`、mock @vue/repl 测试 `useMultiCompiler` | Vitest + @vue/test-utils |
| components | 组件渲染、用户交互（输入/发送/取消/tab 切换/代码编辑） | Vitest + @vue/test-utils |
| 集成 | 完整流程：输入 → 流式 → 编译 → 渲染 | 手动验证 |

## 13. 路由变更

```typescript
// router/index.ts
const routes = [
  { path: '/', name: 'Generation', component: GenerationView },
  { path: '/about', name: 'About', component: About },
]
```

旧 Home.vue 被 GenerationView.vue 替代。
