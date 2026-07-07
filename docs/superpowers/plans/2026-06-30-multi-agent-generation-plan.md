# Multi-Agent AI Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 AI 生成子应用从单次问答升级为多智能体三阶段编排（需求分析 → 详细设计 → 代码实现），每阶段产出可查看/编辑，用户确认后推进。

**Architecture:** 纯前端编排 — 新增 `useMultiAgent` composable 管理状态机，每个阶段调用现有 `POST /api/v1/chat/stream` 传递不同 system prompt。不改后端。

**Tech Stack:** Vue 3 + TypeScript + Pinia + Tailwind CSS，复用共享 `MarkdownRenderer`，复用现有 `useCodeParser`/`useMultiCompiler`/`usePreviewRenderer`

---

### Task 1: 扩展类型定义

**Files:**
- Modify: `packages/ai-generation-app/src/types/generation.ts`

- [ ] **Step 1: 添加阶段、Tab、产出类型**

```typescript
// 在现有类型定义之后追加：

/** 工作流阶段 */
export type Stage = 'idle' | 'analysis' | 'design' | 'code'

/** 阶段状态 */
export type StageStatus = 'pending' | 'active' | 'done'

/** 各阶段产出 */
export interface StageOutputs {
  analysis: string | null
  design: string | null
}

/** 代码实现阶段 Tab */
export type CodeViewTab = 'preview' | 'files'

/** 右侧面板视图 */
export type RightPanelView = 'stage-output' | 'preview' | 'files'

/** 步骤条节点定义 */
export interface StepNode {
  key: Stage
  label: string
  status: StageStatus
}

/** ChatMessage 增加阶段标记 */
// ChatMessage 接口新增可选字段 stage?: Stage
// 注意：需要修改已有 ChatMessage 接口
```

- [ ] **Step 2: 修改 ChatMessage 接口添加 stage 字段**

```typescript
// 修改 ChatMessage 接口
export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  codeBlocks: ParsedCodeBlock[]
  timestamp: number
  isStreaming: boolean
  stage?: Stage  // ← 新增：消息所属阶段
}
```

- [ ] **Step 3: 提交**

```bash
git add packages/ai-generation-app/src/types/generation.ts
git commit -m "feat(types): add multi-agent stage, tab, and output types"
```

---

### Task 2: 扩展 Store

**Files:**
- Modify: `packages/ai-generation-app/src/stores/generation.ts`

- [ ] **Step 1: 添加新 state 字段**

在现有 state 声明区域（`isStreaming` 之后）添加：

```typescript
// ── 多智能体阶段状态 ──
const stage = ref<Stage>('idle')
const stageStatus = ref<Record<string, StageStatus>>({
  analysis: 'pending',
  design: 'pending',
  code: 'pending',
})
const stageOutputs = ref<StageOutputs>({
  analysis: null,
  design: null,
})
const codeViewTab = ref<CodeViewTab>('preview')
const rightPanelView = ref<RightPanelView>('preview')
```

- [ ] **Step 2: 添加新 getters**

在 `activeFileEntry` 之后添加：

```typescript
const currentStepNodes = computed<StepNode[]>(() => {
  const stages: Array<{ key: 'analysis' | 'design' | 'code'; label: string }> = [
    { key: 'analysis', label: '需求分析' },
    { key: 'design', label: '详细设计' },
    { key: 'code', label: '代码实现' },
  ]
  return stages.map((s) => ({
    key: s.key,
    label: s.label,
    status: stageStatus.value[s.key] as StageStatus,
  }))
})

const isStageDone = computed(() => (s: 'analysis' | 'design' | 'code') => {
  return stageStatus.value[s] === 'done'
})
```

- [ ] **Step 3: 添加新 actions**

在 `resetAll()` 之前添加：

```typescript
function setStage(s: Stage): void {
  stage.value = s
}

function setStageStatus(key: string, status: StageStatus): void {
  stageStatus.value[key] = status
}

function setStageOutput(stageKey: 'analysis' | 'design', content: string): void {
  stageOutputs.value[stageKey] = content
}

function setCodeViewTab(tab: CodeViewTab): void {
  codeViewTab.value = tab
  rightPanelView.value = tab
}

function setRightPanelView(view: RightPanelView): void {
  rightPanelView.value = view
}

function enterCodeStage(): void {
  stage.value = 'code'
  stageStatus.value.code = 'active'
  rightPanelView.value = 'preview'
  codeViewTab.value = 'preview'
}

function completeCurrentStage(): void {
  const current = stage.value
  if (current === 'analysis' || current === 'design') {
    stageStatus.value[current] = 'done'
  }
}

function resetAll(): void {
  messages.value = []
  files.value = new Map()
  activeFile.value = null
  isStreaming.value = false
  compiledOutput.value = ''
  compileError.value = null
  stage.value = 'idle'
  stageStatus.value = { analysis: 'pending', design: 'pending', code: 'pending' }
  stageOutputs.value = { analysis: null, design: null }
  codeViewTab.value = 'preview'
  rightPanelView.value = 'preview'
}
```

- [ ] **Step 4: 更新 return 导出**

在 return 对象中新增导出：`stage`, `stageStatus`, `stageOutputs`, `codeViewTab`, `rightPanelView`, `currentStepNodes`, `isStageDone`, `setStage`, `setStageStatus`, `setStageOutput`, `setCodeViewTab`, `setRightPanelView`, `enterCodeStage`, `completeCurrentStage`

- [ ] **Step 5: 提交**

```bash
git add packages/ai-generation-app/src/stores/generation.ts
git commit -m "feat(store): add multi-agent stage state, getters, and actions"
```

---

### Task 3: 创建 Agent System Prompts

**Files:**
- Create: `packages/ai-generation-app/src/composables/useStagePrompts.ts`

- [ ] **Step 1: 写入三个 Agent 的 system prompt 模板**

```typescript
// src/composables/useStagePrompts.ts
import { useComponentDocs } from './useComponentDocs'
import type { ComponentLibrary } from '@/types/generation'

export function useStagePrompts() {
  const { getSystemPrompt } = useComponentDocs()

  function getAnalysisPrompt(): string {
    return `你是资深产品需求分析师。用户会描述一个前端应用需求，你需要通过提问来补充不明确的细节。

**工作流程：**
1. 分析用户输入，识别需求中不够明确的地方（功能边界、交互细节、数据展示、技术偏好等）
2. 每次提出 1-2 个具体问题，给用户提供可选项，引导用户补充
3. 当需求信息充分后（通常 2-4 轮问答），输出结构化的需求规格文档

**提问规则：**
- 每次最多 2 个问题，聚焦最关键的模糊点
- 尽量给出可选项让用户选择，而不是开放式提问
- 当用户回答了所有问题且没有新疑点时，立即输出需求规格文档

**最终输出格式：**
当你认为需求已经足够清晰时，请以下面格式输出：

## 需求规格文档

### 功能概述
[一段话描述应用的核心功能]

### 页面布局
- 布局结构: [如：左右分栏 / 上中下 / 卡片网格]
- 主要区域: [列出页面的主要区块]

### 交互行为
- [交互点1]: [描述]
- [交互点2]: [描述]

### 数据展示
- [数据项]: [展示方式，如表格/列表/卡片]

### 技术要求
- 组件库: [用户选择的组件库]
- 响应式: [是/否]
- 其他: [状态管理/路由需求等]

**重要：** 只有当你确认需求已足够完整时才输出上述文档。文档一旦输出即视为分析完成。`
  }

  function getDesignPrompt(): string {
    return `你是资深前端架构师。你会收到一份需求规格文档，请基于它输出前端详细设计方案。

**工作规则：**
1. 仔细阅读需求规格文档的每个部分
2. 设计组件树结构、数据流、样式方案
3. 确定文件拆分策略（单文件 or 多文件工程）
4. **只输出设计方案，绝对不要写代码**

**输出格式：**

## 详细设计方案

### 组件树结构
\`\`\`
App.vue
├── ComponentA.vue
│   ├── SubComponentB.vue
│   └── SubComponentC.vue
└── ComponentD.vue
\`\`\`

### 数据流设计
- Props 传递: [描述父→子数据流向]
- Events: [描述子→父通信]
- Store: [是否需要 Pinia store，store 的结构]

### 样式方案
- 布局方式: [Flex / Grid / 其他]
- 响应式策略: [断点 / 自适应方案]
- 主题/颜色: [描述]

### 文件拆分方案
- 文件列表: [列出所有需要创建的文件]
- 每个文件的职责: [简述]

### 关键实现要点
- [要点1]
- [要点2]

**重要：** 只输出上述设计方案文档，不输出代码。`
  }

  function getCodeGenPrompt(lib: ComponentLibrary): string {
    const componentDocs = getSystemPrompt(lib)
    return `你是资深 Vue 3 前端全栈工程师。你会收到需求规格文档和详细设计方案，请基于它们生成可运行的完整前端应用代码。

**技术栈：**
- Vue 3 Composition API + <script setup lang="ts">
- TypeScript
- ${lib === 'tailwind' ? 'Tailwind CSS 工具类' : lib + ' 组件库'}
- 需要时使用 Pinia 状态管理、vue-router 路由

**输出规则：**
- 简单应用（单一页面、少量组件）→ 输出单个 .vue SFC 文件
- 复杂应用（多页面/多组件/状态管理）→ 输出多文件工程，每个文件以 ## path/filename 标记

**文件标记格式：**
## src/App.vue
\`\`\`vue
<template>...</template>
<script setup lang="ts">...</script>
\`\`\`

## src/components/Example.vue
\`\`\`vue
...
\`\`\`

## src/stores/useExampleStore.ts
\`\`\`typescript
...
\`\`\`

${componentDocs}

**重要：** 直接输出代码，不需要额外说明文字。每个文件必须以 "## 文件路径" 开头，代码紧跟其后。`
  }

  return { getAnalysisPrompt, getDesignPrompt, getCodeGenPrompt }
}
```

- [ ] **Step 2: 提交**

```bash
git add packages/ai-generation-app/src/composables/useStagePrompts.ts
git commit -m "feat: add multi-agent stage system prompt templates"
```

---

### Task 4: 扩展 useStreamChat 支持外部 messages

**Files:**
- Modify: `packages/ai-generation-app/src/composables/useStreamChat.ts`

- [ ] **Step 1: 添加 `messages` 可选参数**

将 `send` 函数签名从：

```typescript
async function send(content: string, lib?: ComponentLibrary): Promise<void> {
```

改为支持外部传入完整 messages 数组（用于详细设计和代码实现阶段的上下文传递）：

```typescript
// 新增导出类型
export interface StreamSendOptions {
  /** 用户输入的文本内容（需求分析阶段使用） */
  content?: string
  /** 组件库 */
  lib?: ComponentLibrary
  /** 外部传入的完整 messages 数组（详细设计/代码实现阶段使用），优先级高于 content */
  messages?: Array<{ role: string; content: string }>
  /** 消息所属阶段 */
  stage?: 'analysis' | 'design' | 'code'
}
```

- [ ] **Step 2: 修改 send 函数体**

```typescript
async function send(opts: StreamSendOptions): Promise<void> {
  const { content, lib, messages: externalMessages, stage: msgStage } = opts
  error.value = null
  if (lib) store.setCurrentLib(lib)

  // demand analysis mode — add user message
  if (content) {
    const userMsg: ChatMessage = {
      id: generateId(),
      role: 'user',
      content,
      codeBlocks: [],
      timestamp: Date.now(),
      isStreaming: false,
      stage: msgStage,
    }
    store.addMessage(userMsg)
  }

  // create empty assistant message
  const assistantMsg: ChatMessage = {
    id: generateId(),
    role: 'assistant',
    content: '',
    codeBlocks: [],
    timestamp: Date.now(),
    isStreaming: true,
    stage: msgStage,
  }
  store.addMessage(assistantMsg)
  store.isStreaming = true

  // build request body
  abortController = new AbortController()

  const requestMessages = externalMessages ?? [
    { role: 'system', content: getSystemPrompt() },
    ...store.messages
      .filter((m) => !m.isStreaming)
      .map((m) => ({ role: m.role, content: m.content })),
  ]

  // 后续 fetch 逻辑不变...
```

- [ ] **Step 3: 更新 cancel 函数签名对应的引用**

ChatPanel 中对 `send()` 的调用需要适配新签名（将在 Task 10 中统一处理）。

- [ ] **Step 4: 提交**

```bash
git add packages/ai-generation-app/src/composables/useStreamChat.ts
git commit -m "feat(useStreamChat): support external messages for multi-agent context passing"
```

---

### Task 5: 创建 useMultiAgent composable

**Files:**
- Create: `packages/ai-generation-app/src/composables/useMultiAgent.ts`

- [ ] **Step 1: 写入状态机编排逻辑**

```typescript
// src/composables/useMultiAgent.ts
import { ref, readonly, type Ref } from 'vue'
import { useGenerationStore } from '@/stores/generation'
import { useStreamChat } from './useStreamChat'
import { useStagePrompts } from './useStagePrompts'
import type { Stage, StageStatus, ComponentLibrary } from '@/types/generation'

export function useMultiAgent() {
  const store = useGenerationStore()
  const { send, cancel: cancelStream, error: streamError } = useStreamChat()
  const { getAnalysisPrompt, getDesignPrompt, getCodeGenPrompt } = useStagePrompts()

  const isTransitioning = ref(false)

  // ── 阶段推进 ──

  /** 启动需求分析阶段 */
  async function startAnalysis(userContent: string, lib: ComponentLibrary): Promise<void> {
    store.setStage('analysis')
    store.setStageStatus('analysis', 'active')
    store.setRightPanelView('stage-output')

    await send({
      content: userContent,
      lib,
      messages: [
        { role: 'system', content: getAnalysisPrompt() },
        { role: 'user', content: userContent },
      ],
      stage: 'analysis',
    })
    // 流结束后不自动标记完成 — 由用户判断是否推进
  }

  /** 需求分析阶段继续对话（用户回答 Agent 的提问） */
  async function continueAnalysis(userContent: string): Promise<void> {
    // 复用 send，不带 system prompt（已在首轮注入）
    await send({
      content: userContent,
      lib: store.currentLib,
      stage: 'analysis',
    })
  }

  /** 用户确认需求分析，进入详细设计 */
  async function confirmAnalysis(): Promise<void> {
    // 保存需求分析产出（最后一条 assistant 消息的内容）
    const lastAssistant = store.lastAssistantMessage
    if (lastAssistant) {
      store.setStageOutput('analysis', lastAssistant.content)
    }
    store.completeCurrentStage()

    // 启动详细设计
    isTransitioning.value = true
    store.setStage('design')
    store.setStageStatus('design', 'active')
    store.setRightPanelView('stage-output')

    const spec = store.stageOutputs.analysis || ''
    await send({
      lib: store.currentLib,
      messages: [
        { role: 'system', content: getDesignPrompt() },
        { role: 'user', content: `请基于以下需求规格文档输出详细设计方案：\n\n${spec}` },
      ],
      stage: 'design',
    })
    isTransitioning.value = false
  }

  /** 用户确认详细设计，进入代码实现 */
  async function confirmDesign(): Promise<void> {
    const lastAssistant = store.lastAssistantMessage
    if (lastAssistant) {
      store.setStageOutput('design', lastAssistant.content)
    }
    store.completeCurrentStage()

    isTransitioning.value = true
    store.enterCodeStage()

    const spec = store.stageOutputs.analysis || ''
    const design = store.stageOutputs.design || ''
    await send({
      lib: store.currentLib,
      messages: [
        { role: 'system', content: getCodeGenPrompt(store.currentLib) },
        { role: 'user', content: `需求规格：\n${spec}\n\n设计方案：\n${design}\n\n请生成完整代码。` },
      ],
      stage: 'code',
    })
    isTransitioning.value = false
  }

  /** 取消当前请求 */
  function cancel(): void {
    cancelStream()
  }

  /** 判断当前阶段是否完成（最后一条 assistant 消息流式结束） */
  function isCurrentStageFinished(): boolean {
    if (store.isStreaming) return false
    const last = store.lastAssistantMessage
    return last !== null && !last.isStreaming && last.content.length > 0
  }

  /** 点击已完成节点，查看产出 */
  function viewStageOutput(stageKey: 'analysis' | 'design'): void {
    store.setStage(stageKey) // 临时切换到该阶段以渲染 StageOutput
    store.setRightPanelView('stage-output')
  }

  /** 返回当前活跃阶段的视图 */
  function backToCurrentStage(): void {
    const current = store.stage
    if (current === 'code') {
      store.setRightPanelView(store.codeViewTab)
    } else if (current === 'analysis' || current === 'design') {
      store.setRightPanelView('stage-output')
    }
  }

  return {
    startAnalysis,
    continueAnalysis,
    confirmAnalysis,
    confirmDesign,
    cancel,
    isTransitioning: readonly(isTransitioning) as Ref<boolean>,
    streamError,
    isCurrentStageFinished,
    viewStageOutput,
    backToCurrentStage,
  }
}
```

- [ ] **Step 2: 提交**

```bash
git add packages/ai-generation-app/src/composables/useMultiAgent.ts
git commit -m "feat: add useMultiAgent composable for three-stage orchestration"
```

---

### Task 6: 创建 StepProgress 组件

**Files:**
- Create: `packages/ai-generation-app/src/components/StepProgress.vue`

- [ ] **Step 1: 写入步骤条组件**

```vue
<!-- src/components/StepProgress.vue -->
<script setup lang="ts">
import type { StepNode, Stage } from '@/types/generation'

defineProps<{
  nodes: StepNode[]
  currentStage: Stage
}>()

const emit = defineEmits<{
  'node-click': [node: StepNode]
}>()

function statusClass(status: string): string {
  switch (status) {
    case 'done': return 'text-green-600 border-green-500 bg-green-50'
    case 'active': return 'text-blue-600 border-blue-500 bg-blue-50'
    default: return 'text-gray-400 border-gray-300 bg-white'
  }
}

function dotClass(status: string): string {
  switch (status) {
    case 'done': return 'bg-green-500 border-green-500'
    case 'active': return 'bg-blue-500 border-blue-500 animate-pulse'
    default: return 'bg-gray-300 border-gray-300'
  }
}

function lineClass(from: string, to: string): string {
  if (from === 'done' && to === 'done') return 'bg-green-400'
  if (from === 'done' && to === 'active') return 'bg-green-400'
  return 'bg-gray-300'
}
</script>

<template>
  <div class="step-progress flex items-center justify-center gap-0 px-6 py-4 bg-gray-50 border-b border-gray-200">
    <template v-for="(node, index) in nodes" :key="node.key">
      <!-- 连线（非首节点） -->
      <div
        v-if="index > 0"
        class="flex-1 h-0.5 mx-2 min-w-[40px]"
        :class="lineClass(nodes[index - 1]!.status, node.status)"
      />
      <!-- 节点 -->
      <button
        class="flex flex-col items-center gap-1.5 transition-colors"
        :class="[
          node.status === 'done'
            ? 'cursor-pointer hover:opacity-80'
            : 'cursor-default',
        ]"
        :disabled="node.status !== 'done'"
        @click="emit('node-click', node)"
      >
        <span
          class="w-8 h-8 rounded-full border-2 flex items-center justify-center text-xs font-bold transition-all"
          :class="dotClass(node.status)"
        >
          <span v-if="node.status === 'done'">✓</span>
          <span v-else>{{ index + 1 }}</span>
        </span>
        <span
          class="text-xs whitespace-nowrap font-medium"
          :class="{
            'text-green-600': node.status === 'done',
            'text-blue-600 font-semibold': node.status === 'active',
            'text-gray-400': node.status === 'pending',
          }"
        >
          {{ node.label }}
        </span>
      </button>
    </template>
  </div>
</template>
```

- [ ] **Step 2: 提交**

```bash
git add packages/ai-generation-app/src/components/StepProgress.vue
git commit -m "feat: add StepProgress component with three nodes and line connectors"
```

---

### Task 7: 创建 StageOutput 组件

**Files:**
- Create: `packages/ai-generation-app/src/components/StageOutput.vue`

- [ ] **Step 1: 写入阶段产出查看/编辑组件**

```vue
<!-- src/components/StageOutput.vue -->
<script setup lang="ts">
import { ref, computed } from 'vue'
import MarkdownRenderer from '@ai-design/shared/components/MarkdownRenderer.vue'

const props = defineProps<{
  title: string
  content: string | null
}>()

const emit = defineEmits<{
  'save': [content: string]
}>()

const isEditing = ref(false)
const editContent = ref('')

function startEdit(): void {
  editContent.value = props.content || ''
  isEditing.value = true
}

function saveEdit(): void {
  emit('save', editContent.value)
  isEditing.value = false
}

function cancelEdit(): void {
  isEditing.value = false
}

const stageLabel = computed(() => {
  return props.title || '阶段产出'
})
</script>

<template>
  <div class="stage-output flex flex-col h-full">
    <div class="px-4 py-2 border-b border-gray-200 bg-gray-50 flex items-center justify-between">
      <h3 class="text-sm font-semibold text-gray-700">{{ stageLabel }}</h3>
      <button
        v-if="!isEditing && content"
        class="text-xs px-2 py-1 rounded border border-gray-300 text-gray-600 hover:bg-gray-100 transition-colors"
        @click="startEdit"
      >
        ✏️ 编辑
      </button>
    </div>

    <div class="flex-1 overflow-y-auto p-4">
      <div v-if="!content && !isEditing" class="text-center text-gray-400 mt-8">
        <p>等待阶段完成...</p>
      </div>

      <!-- 查看模式 -->
      <MarkdownRenderer v-if="!isEditing && content" :content="content" />

      <!-- 编辑模式 -->
      <div v-if="isEditing" class="flex flex-col h-full gap-2">
        <textarea
          v-model="editContent"
          class="flex-1 w-full border border-gray-300 rounded-lg p-3 text-sm font-mono resize-none focus:outline-none focus:ring-2 focus:ring-blue-500"
          rows="15"
        />
        <div class="flex gap-2 justify-end">
          <button
            class="px-3 py-1.5 text-xs rounded border border-gray-300 text-gray-600 hover:bg-gray-100"
            @click="cancelEdit"
          >
            取消
          </button>
          <button
            class="px-3 py-1.5 text-xs rounded bg-blue-600 text-white hover:bg-blue-700"
            @click="saveEdit"
          >
            保存修改
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
```

- [ ] **Step 2: 提交**

```bash
git add packages/ai-generation-app/src/components/StageOutput.vue
git commit -m "feat: add StageOutput component with view/edit modes"
```

---

### Task 8: 创建 TabBar 组件

**Files:**
- Create: `packages/ai-generation-app/src/components/TabBar.vue`

- [ ] **Step 1: 写入水平 Tab 切换组件**

```vue
<!-- src/components/TabBar.vue -->
<script setup lang="ts">
import type { CodeViewTab } from '@/types/generation'

defineProps<{
  tabs: Array<{ key: CodeViewTab; label: string }>
  activeTab: CodeViewTab
}>()

const emit = defineEmits<{
  'select': [tab: CodeViewTab]
}>()
</script>

<template>
  <div class="tab-bar flex border-b border-gray-200 bg-gray-50">
    <button
      v-for="tab in tabs"
      :key="tab.key"
      class="px-4 py-2 text-sm font-medium transition-colors border-b-2 -mb-px"
      :class="activeTab === tab.key
        ? 'border-blue-500 text-blue-600'
        : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
      "
      @click="emit('select', tab.key)"
    >
      {{ tab.label }}
    </button>
  </div>
</template>
```

- [ ] **Step 2: 提交**

```bash
git add packages/ai-generation-app/src/components/TabBar.vue
git commit -m "feat: add TabBar component for horizontal tab switching"
```

---

### Task 9: 创建 FileExplorer 组件

**Files:**
- Create: `packages/ai-generation-app/src/components/FileExplorer.vue`

- [ ] **Step 1: 写入文件树 + 代码查看器组件**

```vue
<!-- src/components/FileExplorer.vue -->
<script setup lang="ts">
import { ref, computed } from 'vue'
import { useGenerationStore } from '@/stores/generation'
import type { FileEntry } from '@/types/generation'

const store = useGenerationStore()
const selectedFile = ref<string | null>(null)

// 基于 files Map 构建文件列表
const fileEntries = computed(() => {
  return Array.from(store.files.values())
})

// 分组：按目录
const fileTree = computed(() => {
  const tree: Record<string, FileEntry[]> = {}
  for (const entry of fileEntries.value) {
    const dir = entry.filename.includes('/')
      ? entry.filename.substring(0, entry.filename.lastIndexOf('/'))
      : '/'
    if (!tree[dir]) tree[dir] = []
    tree[dir]!.push(entry)
  }
  return tree
})

const currentFile = computed(() => {
  if (!selectedFile.value) return null
  return store.files.get(selectedFile.value) ?? null
})

function selectFile(filename: string): void {
  selectedFile.value = filename
}

// 默认选中第一个文件
if (!selectedFile.value && fileEntries.value.length > 0) {
  selectedFile.value = fileEntries.value[0]!.filename
}

function languageClass(lang: string): string {
  const map: Record<string, string> = {
    vue: 'text-green-600',
    typescript: 'text-blue-600',
    javascript: 'text-yellow-600',
    css: 'text-pink-600',
  }
  return map[lang] || 'text-gray-600'
}
</script>

<template>
  <div class="file-explorer flex h-full bg-white">
    <!-- 左侧文件树 -->
    <div class="w-[200px] min-w-[160px] border-r border-gray-200 overflow-y-auto bg-gray-50">
      <div v-for="(entries, dir) in fileTree" :key="dir">
        <div
          v-if="dir !== '/'"
          class="px-3 py-1.5 text-xs text-gray-500 font-medium uppercase tracking-wide"
        >
          {{ dir }}
        </div>
        <div
          v-for="entry in entries"
          :key="entry.filename"
          class="px-3 py-1.5 text-xs cursor-pointer flex items-center gap-1.5 hover:bg-gray-100 transition-colors"
          :class="{
            'bg-blue-50 text-blue-700 font-medium': selectedFile === entry.filename,
            'text-gray-700': selectedFile !== entry.filename,
          }"
          @click="selectFile(entry.filename)"
        >
          <span class="font-mono" :class="languageClass(entry.language)">●</span>
          <span class="truncate font-mono">{{ entry.filename.split('/').pop() }}</span>
        </div>
      </div>

      <div v-if="fileEntries.length === 0" class="p-4 text-center text-gray-400 text-xs">
        暂无文件 — 等待代码生成
      </div>
    </div>

    <!-- 右侧代码查看器 -->
    <div class="flex-1 overflow-y-auto bg-[#1e1e2e]">
      <div v-if="currentFile" class="p-4">
        <div class="text-xs text-gray-400 mb-2 font-mono">
          {{ currentFile.filename }}
          <span class="ml-2" :class="languageClass(currentFile.language)">
            ({{ currentFile.language }})
          </span>
        </div>
        <pre class="text-sm text-gray-200 font-mono whitespace-pre-wrap"><code>{{ currentFile.content }}</code></pre>
      </div>
      <div v-else class="p-4 text-center text-gray-500 text-sm">
        选择文件查看代码
      </div>
    </div>
  </div>
</template>
```

- [ ] **Step 2: 提交**

```bash
git add packages/ai-generation-app/src/components/FileExplorer.vue
git commit -m "feat: add FileExplorer component with file tree and code viewer"
```

---

### Task 10: 改造 ChatPanel 支持多阶段

**Files:**
- Modify: `packages/ai-generation-app/src/components/ChatPanel.vue`

- [ ] **Step 1: 重写 ChatPanel 脚本**

完整替换 `<script setup>` 部分：

```vue
<!-- src/components/ChatPanel.vue -->
<script setup lang="ts">
import { ref, watch, nextTick, computed } from 'vue'
import { useGenerationStore } from '@/stores/generation'
import { useMultiAgent } from '@/composables/useMultiAgent'
import ChatInput from './ChatInput.vue'
import type { ComponentLibrary } from '@/types/generation'

const store = useGenerationStore()
const {
  startAnalysis,
  continueAnalysis,
  confirmAnalysis,
  confirmDesign,
  cancel: cancelAgent,
  isTransitioning,
  isCurrentStageFinished,
} = useMultiAgent()

const messagesContainer = ref<HTMLElement | null>(null)
const inputText = ref('')

// 自动滚到底部
watch(
  () => store.lastAssistantMessage?.content,
  async () => {
    await nextTick()
    if (messagesContainer.value) {
      messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
    }
  },
)

// 是否可以确认当前阶段（需求分析/设计阶段完成且不在流式中）
const canConfirm = computed(() => {
  const stage = store.stage
  if (stage !== 'analysis' && stage !== 'design') return false
  return isCurrentStageFinished()
})

// 按钮文案
const confirmLabel = computed(() => {
  if (store.stage === 'analysis') return '确认需求 → 进入详细设计'
  if (store.stage === 'design') return '确认方案 → 进入代码实现'
  return '确认'
})

function handleSend(content: string, lib: ComponentLibrary): void {
  if (store.stage === 'idle' || store.stage === 'analysis') {
    if (store.stage === 'idle') {
      startAnalysis(content, lib)
    } else {
      continueAnalysis(content)
    }
  }
}

function handleConfirm(): void {
  if (store.stage === 'analysis') {
    confirmAnalysis()
  } else if (store.stage === 'design') {
    confirmDesign()
  }
}

// 阶段标签样式
function stageLabel(stage?: string): string {
  const map: Record<string, string> = {
    analysis: '需求分析',
    design: '详细设计',
    code: '代码实现',
  }
  return stage ? map[stage] || '' : ''
}

function stageBadgeClass(stage?: string): string {
  switch (stage) {
    case 'analysis': return 'bg-purple-100 text-purple-700'
    case 'design': return 'bg-orange-100 text-orange-700'
    case 'code': return 'bg-green-100 text-green-700'
    default: return 'bg-gray-100 text-gray-500'
  }
}
</script>
```

- [ ] **Step 2: 更新模板**

在消息 `v-for` 循环中，每条消息的头部添加阶段标签：

```vue
<template>
  <div class="chat-panel flex flex-col h-full bg-white">
    <div class="px-4 py-3 border-b border-gray-200 bg-gray-50">
      <h2 class="text-sm font-semibold text-gray-700">AI 代码生成</h2>
    </div>

    <div ref="messagesContainer" class="flex-1 overflow-y-auto px-4 py-3 space-y-4">
      <div v-if="store.messages.length === 0" class="text-center text-gray-400 mt-8">
        <p class="text-lg mb-2">👋 描述你想要生成的组件</p>
        <p class="text-xs">例如："用表格展示用户列表，包含姓名、邮箱、状态列"</p>
      </div>

      <div
        v-for="msg in store.messages"
        :key="msg.id"
        :class="[
          'message flex',
          msg.role === 'user' ? 'justify-end' : 'justify-start',
        ]"
      >
        <div
          :class="[
            'max-w-[90%] rounded-lg px-4 py-2.5 text-sm',
            msg.role === 'user'
              ? 'bg-blue-600 text-white'
              : 'bg-gray-100 text-gray-800',
          ]"
        >
          <!-- 阶段标签 + 流式指示器 -->
          <div v-if="msg.stage" class="flex items-center gap-2 mb-1">
            <span class="text-[10px] px-1.5 py-0.5 rounded-full font-medium" :class="stageBadgeClass(msg.stage)">
              {{ stageLabel(msg.stage) }}
            </span>
            <span
              v-if="msg.isStreaming"
              class="text-[10px] text-blue-500 animate-pulse"
            >
              生成中...
            </span>
          </div>

          <!-- 文本内容 -->
          <div v-if="msg.role === 'user'">{{ msg.content }}</div>
          <div
            v-else
            class="message-content prose prose-sm max-w-none"
            v-html="msg.content
              .replace(/```[\s\S]*?```/g, '')
              .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
              .replace(/\n/g, '<br>')
            "
          />

          <!-- 代码生成卡片 -->
          <div
            v-if="msg.role === 'assistant' && msg.codeBlocks.length > 0"
            class="mt-2 pt-2 border-t border-gray-200"
          >
            <div class="text-xs text-gray-500 mb-1">生成了 {{ msg.codeBlocks.length }} 个文件：</div>
            <div class="flex flex-wrap gap-1">
              <span
                v-for="block in msg.codeBlocks"
                :key="block.filename"
                class="inline-block px-2 py-0.5 text-xs bg-blue-50 text-blue-700 rounded border border-blue-200 font-mono"
              >
                {{ block.filename }}
              </span>
            </div>
          </div>

          <!-- 流式输出指示器 -->
          <span
            v-if="msg.isStreaming && !msg.content"
            class="inline-block w-2 h-4 bg-gray-400 animate-pulse"
          />
        </div>
      </div>

      <!-- 确认推进按钮 -->
      <div v-if="canConfirm" class="flex justify-center">
        <button
          class="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors"
          :disabled="isTransitioning"
          @click="handleConfirm"
        >
          <span v-if="isTransitioning" class="inline-flex items-center gap-1">
            <span class="animate-spin">⏳</span> 推进中...
          </span>
          <span v-else>{{ confirmLabel }}</span>
        </button>
      </div>
    </div>

    <ChatInput
      :is-streaming="store.isStreaming"
      :current-lib="store.currentLib"
      :current-stage="store.stage"
      @send="handleSend"
      @cancel="cancelAgent"
      @update:current-lib="store.setCurrentLib($event)"
    />
  </div>
</template>
```

- [ ] **Step 3: 提交**

```bash
git add packages/ai-generation-app/src/components/ChatPanel.vue
git commit -m "feat(ChatPanel): add stage badges, confirm button, and multi-agent integration"
```

---

### Task 11: 改造 ChatInput 适配多阶段

**Files:**
- Modify: `packages/ai-generation-app/src/components/ChatInput.vue`

- [ ] **Step 1: 添加 currentStage prop，调整 placeholder 和按钮文案**

```vue
<!-- src/components/ChatInput.vue -->
<script setup lang="ts">
import { ref, computed } from 'vue'
import type { ComponentLibrary, Stage } from '@/types/generation'

const emit = defineEmits<{
  send: [content: string, lib: ComponentLibrary]
  cancel: []
  'update:currentLib': [lib: ComponentLibrary]
}>()

const props = defineProps<{
  isStreaming: boolean
  currentLib: ComponentLibrary
  currentStage: Stage  // ← 新增
}>()

const inputText = ref('')
const LIB_OPTIONS: Array<{ key: ComponentLibrary; label: string }> = [
  { key: 'tailwind', label: 'Tailwind CSS' },
  { key: 'antd', label: 'Ant Design Vue' },
  { key: 'element', label: 'Element Plus' },
  { key: 'echarts', label: 'ECharts' },
]

const placeholder = computed(() => {
  switch (props.currentStage) {
    case 'analysis': return '回答需求分析师的问题，或补充需求细节...'
    case 'design': return '对设计方案有修改意见？在这里补充...'
    case 'code': return '对生成的代码有调整要求？在这里说明...'
    default: return '描述你想要生成的组件...'
  }
})

const sendLabel = computed(() => {
  switch (props.currentStage) {
    case 'analysis': return '回复'
    case 'design': return '补充'
    case 'code': return '调整'
    default: return '发送'
  }
})

const canSend = computed(() => {
  // 设计阶段和代码实现阶段：用户可以输入补充意见，但不会自动发送给 agent
  // 只有在 analysis/idle 阶段才能自由发送
  return inputText.value.trim().length > 0
})

function handleSend(): void {
  const text = inputText.value.trim()
  if (!text || props.isStreaming) return
  emit('send', text, props.currentLib)
  inputText.value = ''
}

function handleKeydown(e: KeyboardEvent): void {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  }
}
</script>

<template>
  <div class="chat-input border-t border-gray-200 p-4 bg-white">
    <div class="flex items-center gap-2 mb-2">
      <select
        :value="currentLib"
        :disabled="currentStage !== 'idle'"
        @change="$emit('update:currentLib', ($event.target as HTMLSelectElement).value as ComponentLibrary)"
        class="text-xs border border-gray-300 rounded px-2 py-1 bg-white text-gray-600 disabled:opacity-50 disabled:cursor-not-allowed"
        :title="currentStage !== 'idle' ? '组件库仅在初始阶段可选' : ''"
      >
        <option v-for="opt in LIB_OPTIONS" :key="opt.key" :value="opt.key">
          {{ opt.label }}
        </option>
      </select>
      <span
        v-if="currentStage !== 'idle'"
        class="text-[10px] px-1.5 py-0.5 rounded-full font-medium"
        :class="{
          'bg-purple-100 text-purple-700': currentStage === 'analysis',
          'bg-orange-100 text-orange-700': currentStage === 'design',
          'bg-green-100 text-green-700': currentStage === 'code',
        }"
      >
        {{ currentStage === 'analysis' ? '需求分析中' : currentStage === 'design' ? '详细设计中' : '代码实现中' }}
      </span>
    </div>
    <div class="flex gap-2">
      <textarea
        v-model="inputText"
        @keydown="handleKeydown"
        :disabled="isStreaming"
        :placeholder="placeholder"
        rows="2"
        class="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:bg-gray-100"
      />
      <button
        v-if="!isStreaming"
        @click="handleSend"
        :disabled="!canSend"
        class="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        {{ sendLabel }}
      </button>
      <button
        v-else
        @click="$emit('cancel')"
        class="px-4 py-2 bg-red-600 text-white rounded-lg text-sm font-medium hover:bg-red-700 transition-colors"
      >
        取消
      </button>
    </div>
  </div>
</template>
```

- [ ] **Step 2: 提交**

```bash
git add packages/ai-generation-app/src/components/ChatInput.vue
git commit -m "feat(ChatInput): add currentStage prop, dynamic placeholder and labels"
```

---

### Task 12: 改造 GenerationView 集成所有组件

**Files:**
- Modify: `packages/ai-generation-app/src/views/GenerationView.vue`

- [ ] **Step 1: 重写完整的 GenerationView**

```vue
<!-- src/views/GenerationView.vue -->
<script setup lang="ts">
import { onMounted, computed } from 'vue'
import { useGenerationStore } from '@/stores/generation'
import { useCodeParser } from '@/composables/useCodeParser'
import { useMultiAgent } from '@/composables/useMultiAgent'
import ChatPanel from '@/components/ChatPanel.vue'
import StepProgress from '@/components/StepProgress.vue'
import StageOutput from '@/components/StageOutput.vue'
import TabBar from '@/components/TabBar.vue'
import PreviewFrame from '@/components/PreviewFrame.vue'
import FileExplorer from '@/components/FileExplorer.vue'

const store = useGenerationStore()
const { viewStageOutput, backToCurrentStage } = useMultiAgent()
useCodeParser()

onMounted(() => {
  store.resetAll()
})

const stepNodes = computed(() => store.currentStepNodes)

const currentStageTitle = computed(() => {
  const map: Record<string, string> = {
    analysis: '需求规格文档',
    design: '详细设计方案',
  }
  return map[store.stage] || '阶段产出'
})

const currentStageContent = computed(() => {
  if (store.stage === 'analysis') return store.stageOutputs.analysis
  if (store.stage === 'design') return store.stageOutputs.design
  // 如果是点击已完成节点查看
  return store.stageOutputs[store.stage as 'analysis' | 'design'] || null
})

const codeTabs = [
  { key: 'preview' as const, label: '实时预览' },
  { key: 'files' as const, label: '工程文件' },
]

function handleNodeClick(node: (typeof stepNodes.value)[number]): void {
  if (node.key === 'analysis' || node.key === 'design') {
    viewStageOutput(node.key)
  }
}

function handleStageOutputSave(content: string): void {
  const key = store.stage as 'analysis' | 'design'
  store.setStageOutput(key, content)
}
</script>

<template>
  <div class="generation-view flex h-[calc(100vh-80px)]">
    <!-- 左侧：聊天面板 -->
    <div class="w-[40%] min-w-[320px] border-r border-gray-200">
      <ChatPanel />
    </div>

    <!-- 右侧：步骤条 + 内容区 -->
    <div class="flex-1 min-w-[400px] flex flex-col">
      <StepProgress
        :nodes="stepNodes"
        :current-stage="store.stage"
        @node-click="handleNodeClick"
      />

      <!-- 需求分析/详细设计阶段：展示 StageOutput -->
      <div
        v-if="(store.stage === 'analysis' || store.stage === 'design') && store.rightPanelView === 'stage-output'"
        class="flex-1 flex flex-col"
      >
        <!-- 返回按钮（当查看已完成阶段产出，但当前活跃阶段不是该阶段时显示） -->
        <div
          v-if="store.stageStatus[store.stage] === 'done'"
          class="px-4 py-1.5 bg-gray-50 border-b border-gray-200"
        >
          <button
            class="text-xs text-blue-600 hover:text-blue-800"
            @click="backToCurrentStage()"
          >
            ← 返回当前阶段
          </button>
        </div>
        <StageOutput
          class="flex-1"
          :title="currentStageTitle"
          :content="currentStageContent"
          @save="handleStageOutputSave"
        />
      </div>

      <!-- 代码实现阶段：TabBar + 预览/文件 -->
      <template v-if="store.stage === 'code' && store.rightPanelView !== 'stage-output'">
        <TabBar
          :tabs="codeTabs"
          :active-tab="store.codeViewTab"
          @select="store.setCodeViewTab($event)"
        />

        <div class="flex-1 relative">
          <div v-show="store.codeViewTab === 'preview'" class="absolute inset-0">
            <PreviewFrame />
          </div>
          <div v-show="store.codeViewTab === 'files'" class="absolute inset-0">
            <FileExplorer />
          </div>
        </div>
      </template>

      <!-- 初始状态占位 -->
      <div
        v-if="store.stage === 'idle'"
        class="flex-1 flex items-center justify-center text-gray-400"
      >
        <div class="text-center">
          <p class="text-lg">输入需求，开始 AI 生成</p>
        </div>
      </div>
    </div>
  </div>
</template>
```

- [ ] **Step 2: 提交**

```bash
git add packages/ai-generation-app/src/views/GenerationView.vue
git commit -m "feat(GenerationView): integrate multi-agent flow with StepProgress, StageOutput, TabBar"
```

---

### Task 13: 验证集成

- [ ] **Step 1: 检查 TypeScript 编译**

```bash
cd ai-design-platform-web
npx tsc --noEmit --project packages/ai-generation-app/tsconfig.json 2>&1
```

预期：除 `public-path.ts` 中已有错误外，无新增错误。

- [ ] **Step 2: 检查 imports 完整性**

手动验证所有新组件和 composable 之间的 import 路径正确：
- `useStagePrompts` 从 `useComponentDocs` 导入
- `useMultiAgent` 从 `useStreamChat`、`useStagePrompts` 导入
- `StageOutput` 从 `@ai-design/shared/components/MarkdownRenderer.vue` 导入
- `GenerationView` 从所有新组件导入

- [ ] **Step 3: 提交**

```bash
git add .
git commit -m "chore: verify integration — TypeScript check passes"
```

---

### 依赖关系

```
Task 1 (types)
  └→ Task 2 (store)
       └→ Task 3 (prompts) + Task 4 (useStreamChat)
            └→ Task 5 (useMultiAgent)
                 └→ Task 6 (StepProgress) + Task 7 (StageOutput) + Task 8 (TabBar) + Task 9 (FileExplorer)
                      └→ Task 10 (ChatPanel) + Task 11 (ChatInput) + Task 12 (GenerationView)
                           └→ Task 13 (verify)
```
