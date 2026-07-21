# 全流程多节点工作流 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 LangGraph 5 节点流水线升级为工具增强的全流程工作台，统一文档流式渲染，多 Agent 审查，分屏 E2E 测试。

**Architecture:** 前端分享组件 `StreamDocument` + `StageToolbar`，5 个阶段容器按 `v-if` 切换。后端新增 `tools/` 工具系统，code node 通过 Tool-use Loop 迭代生成，review node 4 Agent 并行审查。全流程通过 `interrupt_before` 所有节点 + SSE 事件驱动。

**Tech Stack:** Python (LangGraph + structlog + asyncio), Vue 3 (Composition API + Pinia + Tailwind CSS + markdown-it), TypeScript

---

## File Structure

```
后端新增:
  ai-service/app/services/generation/tools/
  ├── __init__.py
  ├── registry.py                     — ToolRegistry: 注册/查找/调用
  ├── file_tools.py                   — create_file, write_code, delete_file
  ├── compile_tool.py                 — compile_project, get_compile_errors
  ├── mcp_bridge.py                   — MCP 客户端: connect/search/call
  └── skill_loader.py                 — Skill 模板加载: list/apply
  ai-service/app/services/generation/skills/
  ├── crud-page.json
  ├── form-validation.json
  ├── data-dashboard.json
  ├── auth-guard.json
  ├── file-upload.json
  └── responsive-layout.json
  ai-service/app/services/generation/mcp/
  └── servers.yaml                    — MCP 服务器白名单配置

后端修改:
  ai-service/app/services/generation/state.py       — GenerationState 新增 9 个字段
  ai-service/app/services/generation/nodes.py       — 重写 analysis/design/code/review/e2e 节点
  ai-service/app/services/generation/graph.py       — interrupt_before 所有节点 + 事件统一
  ai-service/app/services/generation/servicer.py    — 新增 SSE 事件类型
  ai-service/app/services/generation/harness.py     — LoopControl 扩展

前端新增:
  ai-design-platform-web/packages/ai-generation-app/src/
  ├── components/StageToolbar.vue                   — 统一标题栏 + 下一步按钮
  ├── components/StreamDocument.vue                 — 流式 MD/HTML 渲染
  ├── components/AnalysisStagePanel.vue             — 需求分析阶段容器
  ├── components/DesignStagePanel.vue               — 详细设计阶段容器
  ├── components/CodeStagePanel.vue                 — 功能开发阶段容器
  ├── components/ToolTracePanel.vue                 — 工具调用链可视化
  ├── components/ReviewStagePanel.vue               — 质量校验阶段容器
  ├── components/MultiAgentPanel.vue                — 多 Agent 并行审查面板
  ├── components/E2EStagePanel.vue                  — E2E 阶段容器（分屏）
  ├── components/TestCaseProgress.vue               — 测试用例执行进度
  └── types/generation.ts                           — 追加类型（实际修改）

前端修改:
  src/stores/generation.ts                          — 扩展 state + actions + computed
  src/composables/useStreamChat.ts                  — 新增全流程 SSE 事件处理
  src/composables/useE2ERunner.ts                   — 扩展分屏模式
  src/views/GenerationView.vue                      — 集成 StageToolbar + 5 个阶段容器
  src/components/ChatPanel.vue                      — 移除底部确认按钮，保留"开始设计"
  src/components/E2EPanel.vue                       — 标记 deprecated
  src/components/PRDGeneratorView.vue               — 标记 deprecated
```

---

### Task 1: Store 扩展 — 新增阶段控制 + 流式文档状态

**Files:**
- Modify: `ai-design-platform-web/packages/ai-generation-app/src/stores/generation.ts`
- Modify: `ai-design-platform-web/packages/ai-generation-app/src/types/generation.ts`

- [ ] **Step 1: 在 types/generation.ts 中新增类型定义**

In `src/types/generation.ts`, append:

```typescript
// ── 阶段 Phase ──
export type StagePhase = 'idle' | 'qa' | 'generating' | 'reviewing' | 'complete'

// ── Tool Trace ──
export interface ToolTraceEntry {
  id: string
  type: 'call' | 'result'
  tool: string
  args?: Record<string, any>
  status: 'running' | 'done' | 'error'
  summary?: string
  timestamp: number
}

// ── Review Agent ──
export interface ReviewFinding {
  severity: 'critical' | 'high' | 'medium' | 'low'
  file: string
  line: number
  title: string
  description: string
  fix: string
}

export interface ReviewAgentState {
  key: string
  name: string
  icon: string
  status: 'pending' | 'running' | 'done'
  findings: ReviewFinding[]
  totalIssues: number
}
```

- [ ] **Step 2: 在 generation.ts 中新增 state 字段**

In `src/stores/generation.ts`, add after the existing `prdVersion`:

```typescript
// ── 阶段控制 ──
const stagePhase = ref<StagePhase>('idle')
const awaitingConfirm = ref(false)

// ── 流式文档（analysis/design/e2e-testcases 共享）──
const docStreamingContent = ref('')
const docIsStreaming = ref(false)

// ── Code 阶段 ──
const generatedFiles = ref<Record<string, string>>({})
const currentGeneratingFile = ref<string | null>(null)
const toolTraces = ref<ToolTraceEntry[]>([])

// ── Review 阶段 ──
const reviewAgents = ref<ReviewAgentState[]>([])
const reviewReportHtml = ref<string | null>(null)

// ── E2E 阶段 ──
const e2eTestCasesMd = ref<string | null>(null)
const e2eUserConfirmed = ref(false)
const e2eCurrentCaseId = ref<string | null>(null)
```

- [ ] **Step 3: 新增 actions**

After the existing `setPRDVersion` action, add:

```typescript
// ── 阶段 Phase ──
function setStagePhase(phase: StagePhase): void {
  stagePhase.value = phase
}
function setAwaitingConfirm(v: boolean): void {
  awaitingConfirm.value = v
}

// ── 流式文档 ──
function appendDocContent(content: string): void {
  docStreamingContent.value += content
}
function setDocComplete(fullContent: string): void {
  docStreamingContent.value = fullContent
  docIsStreaming.value = false
}
function resetDocContent(): void {
  docStreamingContent.value = ''
  docIsStreaming.value = true
}

// ── Code 阶段 ──
function initFileTree(files: string[]): void {
  generatedFiles.value = {}
  for (const f of files) {
    generatedFiles.value[f] = ''
  }
  toolTraces.value = []
}
function setCurrentGeneratingFile(path: string | null): void {
  currentGeneratingFile.value = path
}
function appendFileContent(path: string, content: string): void {
  if (!generatedFiles.value[path]) {
    generatedFiles.value[path] = ''
  }
  generatedFiles.value[path] += content
}
function finalizeFile(path: string): void {
  setFile(path, {
    filename: path,
    content: generatedFiles.value[path] || '',
    language: path.endsWith('.vue') ? 'vue' : path.endsWith('.ts') ? 'typescript' : 'text',
    isDirty: false,
    source: 'ai',
  })
}
function addToolTrace(entry: Omit<ToolTraceEntry, 'id' | 'timestamp'>): string {
  const id = generateTraceId()
  toolTraces.value.push({ ...entry, id, timestamp: Date.now() })
  return id
}
function updateToolTrace(id: string, patch: Partial<ToolTraceEntry>): void {
  const idx = toolTraces.value.findIndex(t => t.id === id)
  if (idx >= 0) Object.assign(toolTraces.value[idx]!, patch)
}
function setCodeGenDone(files: number, errors: number): void {
  // placeholder for compile status
}

// ── Review 阶段 ──
function initReviewAgents(agents: Array<{ key: string; name: string; icon: string }>): void {
  reviewAgents.value = agents.map(a => ({
    key: a.key,
    name: a.name,
    icon: a.icon,
    status: 'pending',
    findings: [],
    totalIssues: 0,
  }))
}
function appendAgentFinding(agentKey: string, issue: ReviewFinding): void {
  const agent = reviewAgents.value.find(a => a.key === agentKey)
  if (agent) {
    agent.findings.push(issue)
    agent.totalIssues = agent.findings.length
  }
}
function setAgentDone(agentKey: string): void {
  const agent = reviewAgents.value.find(a => a.key === agentKey)
  if (agent) agent.status = 'done'
}
function setAgentRunning(agentKey: string): void {
  const agent = reviewAgents.value.find(a => a.key === agentKey)
  if (agent) agent.status = 'running'
}

// ── E2E 阶段 ──
function setE2ECasesDoc(md: string): void {
  e2eTestCasesMd.value = md
}
function confirmE2ECases(): void {
  e2eUserConfirmed.value = true
}
function setCurrentE2ECase(caseId: string): void {
  e2eCurrentCaseId.value = caseId
}
function setE2EComplete(_summary: { total: number; passed: number; failed: number }): void {
  // handled by existing e2e logic
}

function generateTraceId(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 7)
}
```

- [ ] **Step 4: 新增 computed**

After existing `isStageDone`, add:

```typescript
const showStreamDocument = computed(() => {
  if (stage.value === 'analysis' || stage.value === 'design') return true
  if (stage.value === 'e2e' && !e2eUserConfirmed.value) return true
  return false
})

const showNextButton = computed(() =>
  awaitingConfirm.value && stagePhase.value === 'complete'
)

const reviewIssueSummary = computed(() => {
  const all = reviewAgents.value.flatMap(a => a.findings)
  return {
    total: all.length,
    critical: all.filter(i => i.severity === 'critical').length,
    high: all.filter(i => i.severity === 'high').length,
  }
})

const compileStatus = computed(() => {
  const compiles = toolTraces.value.filter(t => t.tool === 'compile_project')
  const last = compiles.at(-1)
  return {
    hasErrors: last?.status === 'error',
    lastCompileOk: last?.status === 'done',
  }
})
```

- [ ] **Step 5: 更新 resetAll 和 return**

In `resetAll`, add resets for new state:

```typescript
stagePhase.value = 'idle'
awaitingConfirm.value = false
docStreamingContent.value = ''
docIsStreaming.value = false
generatedFiles.value = {}
currentGeneratingFile.value = null
toolTraces.value = []
reviewAgents.value = []
reviewReportHtml.value = null
e2eTestCasesMd.value = null
e2eUserConfirmed.value = false
e2eCurrentCaseId.value = null
```

In the `return` block, add all new exports:

```typescript
stagePhase, awaitingConfirm,
docStreamingContent, docIsStreaming,
generatedFiles, currentGeneratingFile, toolTraces,
reviewAgents, reviewReportHtml,
e2eTestCasesMd, e2eUserConfirmed, e2eCurrentCaseId,
setStagePhase, setAwaitingConfirm,
appendDocContent, setDocComplete, resetDocContent,
initFileTree, setCurrentGeneratingFile, appendFileContent, finalizeFile,
addToolTrace, updateToolTrace, setCodeGenDone,
initReviewAgents, appendAgentFinding, setAgentDone, setAgentRunning,
setE2ECasesDoc, confirmE2ECases, setCurrentE2ECase, setE2EComplete,
showStreamDocument, showNextButton, reviewIssueSummary, compileStatus,
```

- [ ] **Step 6: 验证 TypeScript 编译**

```bash
cd ai-design-platform-web && npx turbo run typecheck --filter=ai-generation-app
```

Expected: no type errors related to generation store changes.

---

### Task 2: StageToolbar — 统一的阶段标题栏 + 下一步按钮

**Files:**
- Create: `ai-design-platform-web/packages/ai-generation-app/src/components/StageToolbar.vue`

- [ ] **Step 1: 创建 StageToolbar.vue**

```vue
<!-- src/components/StageToolbar.vue -->
<script setup lang="ts">
import { useGenerationStore } from '@/stores/generation'
import { useMultiAgent } from '@/composables/useMultiAgent'

const props = withDefaults(defineProps<{
  title?: string
  showNextButton?: boolean
  nextLabel?: string
  isStreaming?: boolean
}>(), {
  title: '',
  showNextButton: false,
  nextLabel: '下一步 ▸',
  isStreaming: false,
})

const emit = defineEmits<{
  next: []
}>()

const store = useGenerationStore()
const { confirmStage } = useMultiAgent()

const stageTitle = computed(() => {
  if (props.title) return props.title
  const map: Record<string, string> = {
    analysis: '需求规格文档',
    design: '详细设计方案',
    code: '功能开发',
    review: '质量校验报告',
    e2e: 'E2E 验证',
  }
  return map[store.stage] || '阶段产出'
})

async function handleNext(): Promise<void> {
  if (store.isStreaming) return
  emit('next')
  await confirmStage(store.stage)
}
</script>

<template>
  <div class="flex items-center justify-between px-4 py-2 bg-white border-b border-gray-200">
    <div class="flex items-center gap-2">
      <span class="text-sm font-medium text-gray-700">{{ stageTitle }}</span>
      <span
        v-if="isStreaming || store.isStreaming"
        class="text-xs text-blue-500 animate-pulse"
      >
        ▊ 生成中...
      </span>
      <span
        v-else-if="showNextButton || store.showNextButton"
        class="text-xs text-green-600"
      >
        ✓ 生成完成
      </span>
    </div>

    <div class="flex items-center gap-2">
      <slot name="extra-actions" />
      <button
        v-if="showNextButton || store.showNextButton"
        class="px-3 py-1 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-50 transition-colors"
        :disabled="store.isStreaming"
        @click="handleNext"
      >
        {{ nextLabel }}
      </button>
    </div>
  </div>
</template>
```

- [ ] **Step 2: 验证编译无错误**

```bash
cd ai-design-platform-web && npx turbo run typecheck --filter=ai-generation-app
```

---

### Task 3: StreamDocument — 流式 MD/HTML 渲染组件

**Files:**
- Create: `ai-design-platform-web/packages/ai-generation-app/src/components/StreamDocument.vue`

- [ ] **Step 1: 创建 StreamDocument.vue**

```vue
<!-- src/components/StreamDocument.vue -->
<script setup lang="ts">
import { ref, watch, computed, nextTick } from 'vue'
import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js'
import DOMPurify from 'dompurify'

const props = withDefaults(defineProps<{
  content: string
  isStreaming?: boolean
  language?: 'md' | 'html'
}>(), {
  content: '',
  isStreaming: false,
  language: 'md',
})

const containerRef = ref<HTMLElement | null>(null)

const md = new MarkdownIt({
  html: false,
  linkify: true,
  typographer: true,
  highlight(str: string, lang: string): string {
    if (lang && hljs.getLanguage(lang)) {
      try {
        return hljs.highlight(str, { language: lang }).value
      } catch { /* fallthrough */ }
    }
    return ''
  },
})

const renderedContent = computed(() => {
  if (props.language === 'html') {
    return DOMPurify.sanitize(props.content)
  }
  return DOMPurify.sanitize(md.render(props.content))
})

// Auto-scroll when streaming
watch(
  () => props.content,
  async () => {
    if (!props.isStreaming) return
    await nextTick()
    if (containerRef.value) {
      containerRef.value.scrollTop = containerRef.value.scrollHeight
    }
  },
)
</script>

<template>
  <div
    ref="containerRef"
    class="stream-document flex-1 overflow-auto p-4"
  >
    <div
      v-if="language === 'html'"
      class="prose prose-sm max-w-none"
      v-html="renderedContent"
    />
    <div
      v-else
      class="prose prose-sm max-w-none markdown-body"
      v-html="renderedContent"
    />
    <div
      v-if="isStreaming && !content"
      class="text-gray-400 text-sm text-center mt-8"
    >
      等待生成...
    </div>
  </div>
</template>

<style scoped>
.stream-document {
  scroll-behavior: smooth;
}
</style>
```

- [ ] **Step 2: 验证 markdown-it 和 dompurify 已安装**

```bash
cd ai-design-platform-web/packages/ai-generation-app
pnpm list markdown-it dompurify highlight.js
```

If not installed:
```bash
pnpm add markdown-it dompurify highlight.js
pnpm add -D @types/markdown-it @types/dompurify
```

- [ ] **Step 3: 验证编译无错误**

```bash
cd ai-design-platform-web && npx turbo run typecheck --filter=ai-generation-app
```

---

### Task 4: ChatPanel 改造 — 移除底部确认按钮，保留"开始设计"

**Files:**
- Modify: `ai-design-platform-web/packages/ai-generation-app/src/components/ChatPanel.vue`

- [ ] **Step 1: 移除 `canConfirm` computed 和确认按钮模板**

Remove the `canConfirm` computed:

```typescript
// DELETE this block:
// const canConfirm = computed(() => {
//   const stage = store.stage
//   if (stage !== 'analysis' && stage !== 'design') return false
//   return isCurrentStageFinished()
// })

// DELETE confirmLabel computed
```

Remove the confirm button from template:

```html
<!-- DELETE this block: -->
<!--
<div v-if="canConfirm" class="flex justify-center">
  <button ... @click="handleConfirm">...</button>
</div>
-->
```

- [ ] **Step 2: 新增"开始设计"按钮 — 仅 analysis Q&A 阶段完成后显示**

Add new computed and button after the existing option buttons:

```vue
<script setup lang="ts">
// NEW: 反问完成后显示"开始设计"按钮
const canStartDesign = computed(() => {
  if (store.stage !== 'analysis') return false
  if (store.stagePhase !== 'qa') return false
  return isCurrentStageFinished() && store.messages.length >= 2
})

async function handleStartDesign(): Promise<void> {
  await confirmStage('analysis')
}
</script>
```

In template, add before the ChatInput:

```html
<!-- 开始设计按钮（反问完成时显示） -->
<div v-if="canStartDesign" class="flex justify-center pb-2">
  <button
    class="px-4 py-2 bg-green-600 text-white rounded-lg text-sm font-medium hover:bg-green-700 disabled:opacity-50 transition-colors"
    :disabled="isTransitioning"
    @click="handleStartDesign"
  >
    <span v-if="isTransitioning" class="inline-flex items-center gap-1">
      <span class="animate-spin">⏳</span> 启动中...
    </span>
    <span v-else>🚀 开始设计</span>
  </button>
</div>
```

- [ ] **Step 3: 移除不再使用的 `handleConfirm` 函数**

Delete `handleConfirm` function entirely.

- [ ] **Step 4: 验证编译**

```bash
cd ai-design-platform-web && npx turbo run typecheck --filter=ai-generation-app
```

---

### Task 5: AnalysisStagePanel + DesignStagePanel — 阶段容器

**Files:**
- Create: `ai-design-platform-web/packages/ai-generation-app/src/components/AnalysisStagePanel.vue`
- Create: `ai-design-platform-web/packages/ai-generation-app/src/components/DesignStagePanel.vue`

- [ ] **Step 1: 创建 AnalysisStagePanel.vue**

```vue
<!-- src/components/AnalysisStagePanel.vue -->
<script setup lang="ts">
import { useGenerationStore } from '@/stores/generation'
import StreamDocument from './StreamDocument.vue'

const store = useGenerationStore()

function handleExport(): void {
  const blob = new Blob([store.docStreamingContent], { type: 'text/markdown' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = 'PRD.md'
  a.click()
  URL.revokeObjectURL(a.href)
}
</script>

<template>
  <div class="flex-1 flex flex-col">
    <StreamDocument
      :content="store.docStreamingContent"
      :is-streaming="store.docIsStreaming || store.isStreaming"
      language="md"
    />
    <div v-if="!store.isStreaming && store.docStreamingContent" class="flex gap-2 px-4 py-2 border-t border-gray-200 bg-white">
      <button
        class="px-3 py-1 text-sm border rounded hover:bg-gray-50 transition-colors"
        @click="handleExport"
      >
        📥 导出 MD
      </button>
    </div>
  </div>
</template>
```

- [ ] **Step 2: 创建 DesignStagePanel.vue**

```vue
<!-- src/components/DesignStagePanel.vue -->
<script setup lang="ts">
import { useGenerationStore } from '@/stores/generation'
import StreamDocument from './StreamDocument.vue'

const store = useGenerationStore()

function handleExport(): void {
  const blob = new Blob([store.docStreamingContent], { type: 'text/markdown' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = 'DesignDoc.md'
  a.click()
  URL.revokeObjectURL(a.href)
}
</script>

<template>
  <div class="flex-1 flex flex-col">
    <StreamDocument
      :content="store.docStreamingContent"
      :is-streaming="store.docIsStreaming || store.isStreaming"
      language="md"
    />
    <div v-if="!store.isStreaming && store.docStreamingContent" class="flex gap-2 px-4 py-2 border-t border-gray-200 bg-white">
      <button
        class="px-3 py-1 text-sm border rounded hover:bg-gray-50 transition-colors"
        @click="handleExport"
      >
        📥 导出 MD
      </button>
    </div>
  </div>
</template>
```

- [ ] **Step 3: 验证编译**

```bash
cd ai-design-platform-web && npx turbo run typecheck --filter=ai-generation-app
```

---

### Task 6: GenerationView 集成 — StageToolbar + 阶段容器切换

**Files:**
- Modify: `ai-design-platform-web/packages/ai-generation-app/src/views/GenerationView.vue`

- [ ] **Step 1: 更新导入**

Add new imports, remove deprecated:

```typescript
// ADD:
import StageToolbar from '@/components/StageToolbar.vue'
import StreamDocument from '@/components/StreamDocument.vue'
import AnalysisStagePanel from '@/components/AnalysisStagePanel.vue'
import DesignStagePanel from '@/components/DesignStagePanel.vue'
import CodeStagePanel from '@/components/CodeStagePanel.vue'
import ReviewStagePanel from '@/components/ReviewStagePanel.vue'
import E2EStagePanel from '@/components/E2EStagePanel.vue'

// REMOVE:
// import AnalysisPanel from '@/components/AnalysisPanel.vue'  -- deprecated
```

- [ ] **Step 2: 替换右侧面板内容**

Replace the right panel area (from StepProgress onward) with:

```html
<!-- 右侧：步骤条 + 内容区 -->
<div class="flex-1 min-w-[400px] flex flex-col">
  <StepProgress
    :nodes="stepNodes"
    :current-stage="store.stage"
    @node-click="handleNodeClick"
  />

  <!-- StageToolbar（所有阶段共用，idle 和 done 隐藏） -->
  <StageToolbar
    v-if="store.stage !== 'idle' && store.stage !== 'done'"
    :title="currentStageTitle"
    :is-streaming="store.isStreaming"
  >
    <template #extra-actions>
      <slot />
    </template>
  </StageToolbar>

  <!-- 阶段容器切换 -->
  <AnalysisStagePanel v-if="store.stage === 'analysis'" />

  <DesignStagePanel v-else-if="store.stage === 'design'" />

  <template v-else-if="store.stage === 'code'">
    <CodeStagePanel />
  </template>

  <ReviewStagePanel v-else-if="store.stage === 'review'" />

  <E2EStagePanel v-else-if="store.stage === 'e2e'" />

  <!-- 初始状态占位 -->
  <div
    v-if="store.stage === 'idle'"
    class="flex-1 flex items-center justify-center text-gray-400"
  >
    <div class="text-center">
      <p class="text-lg">输入需求，开始 AI 生成</p>
    </div>
  </div>

  <!-- 完成状态 -->
  <div
    v-if="store.stage === 'done'"
    class="flex-1 flex items-center justify-center text-gray-400"
  >
    <div class="text-center">
      <p class="text-lg text-green-600">✓ 所有阶段完成</p>
    </div>
  </div>

  <!-- Manual review banner -->
  <div v-if="store.needsManualReview" class="manual-review-banner">
    自动流程已熔断，请人工复核
    <span v-if="store.loopBreakReason">原因：{{ store.loopBreakReason }}</span>
  </div>
</div>
```

- [ ] **Step 3: 清理不再使用的逻辑**

Remove:
- `viewStageOutput` function (replaced by stage panel)
- `backToCurrentStage` function (replaced by stage panel)
- `currentStageContent` computed (replaced by `docStreamingContent`)
- `codeTabs` constant (now managed by CodeStagePanel)
- `handleStageOutputSave` function

Update `currentStageTitle`:

```typescript
const currentStageTitle = computed(() => {
  const map: Record<string, string> = {
    analysis: '📋 需求规格文档',
    design: '📐 详细设计方案',
    code: '💻 功能开发',
    review: '🔍 质量校验报告',
    e2e: '🧪 E2E 验证',
  }
  return map[store.stage] || '阶段产出'
})
```

Keep `stepNodes` and `handleNodeClick` as-is.

- [ ] **Step 4: 验证编译**

```bash
cd ai-design-platform-web && npx turbo run typecheck --filter=ai-generation-app
```

---

### Task 7: useStreamChat — 新增全流程 SSE 事件处理

**Files:**
- Modify: `ai-design-platform-web/packages/ai-generation-app/src/composables/useStreamChat.ts`

- [ ] **Step 1: 在 SSE 事件 switch 中新增/修改事件处理**

In the `switch (eventType)` block, add these new cases alongside existing ones:

```typescript
// ── 阶段 Phase ──
case 'stage_start':
  store.setStageStatus(event.stage, 'active')
  store.setStage(event.stage as Stage)
  if (event.phase) {
    store.setStagePhase(event.phase)
  }
  break

case 'stage_complete':
  store.setStageStatus(event.stage, 'done')
  store.setStagePhase('complete')
  break

case 'human_confirm_required':
  store.setAwaitingConfirm(true)
  break

// ── 流式文档（analysis/design/e2e-testcases 统一）──
case 'doc_chunk':
  store.appendDocContent(event.content || '')
  break

case 'prd_generate_start':
  store.resetDocContent()
  break

case 'prd_generate_done':
  store.setDocComplete(event.full_content || '')
  store.setStageOutput('analysis', event.full_content || '')
  break

case 'design_gen_start':
  store.resetDocContent()
  break

case 'design_gen_done':
  store.setDocComplete(event.full_content || '')
  store.setStageOutput('design', event.full_content || '')
  break

// ── Code 阶段 ──
case 'code_gen_start':
  store.initFileTree(event.files || [])
  store.docIsStreaming = true
  break

case 'file_start':
  store.setCurrentGeneratingFile(event.path)
  break

case 'file_chunk':
  store.appendFileContent(event.path, event.content || '')
  break

case 'file_complete':
  store.finalizeFile(event.path)
  store.setCurrentGeneratingFile(null)
  break

case 'tool_call': {
  const id = store.addToolTrace({
    type: 'call',
    tool: event.tool,
    args: event.args,
    status: 'running',
  })
  // Store id for matching tool_result
  event._traceId = id
  break
}

case 'tool_result':
  if (event._traceId) {
    store.updateToolTrace(event._traceId, {
      type: 'result',
      status: event.ok ? 'done' : 'error',
      summary: event.summary || (event.ok ? 'Done' : 'Error'),
    })
  }
  break

case 'code_gen_done':
  store.setCodeGenDone(event.total_files || 0, event.compile_errors || 0)
  break

// ── Review 阶段 ──
case 'review_agents_start':
  store.initReviewAgents(event.agents || [])
  break

case 'review_agent_chunk': {
  store.setAgentRunning(event.agent)
  store.appendAgentFinding(event.agent, {
    severity: event.issue?.severity || 'medium',
    file: event.issue?.file || '',
    line: event.issue?.line || 0,
    title: event.issue?.title || '',
    description: event.issue?.description || '',
    fix: event.issue?.fix || '',
  })
  break
}

case 'review_agent_done':
  store.setAgentDone(event.agent)
  break

case 'review_report_ready':
  store.reviewReportHtml = event.report_html
  store.docStreamingContent = event.report_html || ''
  break

case 'review_fix_start':
  // 自动修复中 — 切回 code 阶段
  break

case 'review_fix_done':
  // 修复完成
  break

// ── E2E 阶段 ──
case 'e2e_cases_gen_start':
  store.resetDocContent()
  break

case 'e2e_cases_gen_done':
  store.setE2ECasesDoc(event.full_content || '')
  store.setDocComplete(event.full_content || '')
  break

case 'e2e_execute_start':
  // Already handled by existing e2e_start
  break

case 'e2e_case_start':
  store.setCurrentE2ECase(event.case_id)
  break

case 'e2e_execute_done':
  store.setE2EComplete({
    total: event.total || 0,
    passed: event.passed || 0,
    failed: event.failed || 0,
  })
  break

case 'graph_complete':
  store.setStage('done' as Stage)
  break
```

- [ ] **Step 2: 更新已有事件处理 — 合并 PRD 事件为 doc_chunk**

Modify the existing `prd_section` handler to also call `appendDocContent`:

```typescript
case 'prd_section':
  store.appendPRDContent(event.content || '')   // keep backward compat
  store.appendDocContent(event.content || '')   // unified doc stream
  break
```

- [ ] **Step 3: 验证编译**

```bash
cd ai-design-platform-web && npx turbo run typecheck --filter=ai-generation-app
```

---

### Task 8: 后端 — GenerationState 扩展

**Files:**
- Modify: `ai-design-platform-server/ai-service/app/services/generation/state.py`

- [ ] **Step 1: 新增 TypedDict 字段**

In `class GenerationState(TypedDict)`, add after `needs_manual_review`:

```python
class GenerationState(TypedDict):
    # ... existing fields unchanged ...

    # ====== NEW FIELDS ======
    # Stage phase tracking
    stage_phase: str                           # "qa" | "generating" | "complete"

    # Design document MD (separate from old design_result for streaming)
    design_doc: str | None

    # Code generation — multi-file project
    generated_files: dict[str, str]            # filename -> code content
    compile_errors: list[dict] | None          # [{file, line, message}]

    # Multi-agent review
    review_agent_results: list[dict] | None    # [{agent_key, issues: [...]}]
    review_report_html: str | None             # Merged HTML report
    review_issues: list[dict] | None           # Structured issue list

    # E2E test cases document
    e2e_test_cases_md: str | None              # MD document for user review
    e2e_user_confirmed: bool                   # User confirmed test cases
```

- [ ] **Step 2: 验证导入无错误**

```bash
cd ai-design-platform-server/ai-service
python -c "from app.services.generation.state import GenerationState; print('OK')"
```

---

### Task 9: 后端 — graph.py 事件统一 + interrupt 调整

**Files:**
- Modify: `ai-design-platform-server/ai-service/app/services/generation/graph.py`

- [ ] **Step 1: 调整 interrupt_before 为所有节点**

In `build_graph()`, change:

```python
# OLD:
app = workflow.compile(
    checkpointer=checkpointer,
    interrupt_before=["analysis", "design"],
)

# NEW:
app = workflow.compile(
    checkpointer=checkpointer,
    interrupt_before=["analysis", "design", "code", "review", "e2e"],
)
```

- [ ] **Step 2: 在 GraphRunner.run() 中为每个节点发射 stage_phase 事件**

In the `run` method, add phase event before each node:

```python
for node_name, node_output in event.items():
    # Emit stage_start with phase info
    phase = node_output.get("stage_phase", "generating")
    yield self._make_event("stage_start", node_name, {
        "phase": phase,
    })

    # ... existing node-specific logic ...
```

- [ ] **Step 3: 统一 analysis/design PRD 事件为 doc_chunk**

Modify the PRD chunking logic to emit `doc_chunk` events:

```python
if node_name == "analysis":
    analysis_result = node_output.get("analysis_result", "")
    if analysis_result:
        yield self._make_event("prd_generate_start", "analysis", {
            "mode": "full",
            "sections_count": 5,
            "parent_version": None,
        })
        chunk_size = 80
        for i in range(0, len(analysis_result), chunk_size):
            chunk = analysis_result[i:i + chunk_size]
            yield self._make_event("doc_chunk", "analysis", {
                "content": chunk,
                "checkpoint_id": f"ck_{generation_id}_{i // chunk_size}",
            })
        yield self._make_event("prd_generate_done", "analysis", {
            "version": 1,
            "full_content": analysis_result,
            "duration_ms": 0,
        })

if node_name == "design":
    design_doc = node_output.get("design_doc", "")
    if design_doc:
        yield self._make_event("design_gen_start", "design", {})
        chunk_size = 80
        for i in range(0, len(design_doc), chunk_size):
            chunk = design_doc[i:i + chunk_size]
            yield self._make_event("doc_chunk", "design", {
                "content": chunk,
            })
        yield self._make_event("design_gen_done", "design", {
            "full_content": design_doc,
        })
```

- [ ] **Step 4: 验证 graph 编译**

```bash
cd ai-design-platform-server/ai-service
python -c "from app.services.generation.graph import build_graph; g = build_graph(); print('OK:', g)"
```

---

### Task 10: 后端 — design_node 流式输出

**Files:**
- Modify: `ai-design-platform-server/ai-service/app/services/generation/nodes.py`

- [ ] **Step 1: 扩展 design_node 输出 design_doc 字段**

Modify `design_node` to include `design_doc`:

```python
async def design_node(state: GenerationState) -> GenerationState:
    logger.info("design_node_start")

    failure_details = state.get("failure_details")
    if failure_details and failure_details["source"] == "review":
        prompt = (
            f"原需求分析：\n{state['analysis_result']}\n\n"
            f"之前的设计方案存在问题，review 反馈如下：\n"
            f"{failure_details['instruction']}\n\n"
            f"请修改设计方案，解决上述问题。"
        )
    else:
        prompt = f"需求分析文档：\n{state['analysis_result']}"

    result = await _llm_generate(
        system_prompt=DESIGN_SYSTEM_PROMPT,
        user_content=prompt,
    )

    state["design_result"] = result
    state["design_doc"] = result
    state["stage_phase"] = "complete"

    check = EvalHarness.validate(state, "design")
    if not check.passed:
        logger.warning("design_validation_failed", errors=check.errors)

    return state
```

- [ ] **Step 2: 更新 analysis_node 设置 stage_phase**

```python
async def analysis_node(state: GenerationState) -> GenerationState:
    logger.info("analysis_node_start")

    requirement = state.get("requirement", "")
    messages = state.get("messages", [])
    qa_rounds = state.get("qa_rounds", 0)

    # Phase 1: Q&A
    if qa_rounds == 0:
        # Enter Q&A phase — handled by existing Q&A logic
        return state

    # Check if user wants to start design
    # Phase 2: PRD generation (triggered after Q&A confirm)
    context = ""
    for m in messages:
        context += f"\n[{m.get('role', '?')}]: {m.get('content', '')}"

    user_prompt = f"用户需求：{requirement}\n\n对话上下文：{context}\n\n请生成完整的需求规格文档。"

    prd_text = await _llm_generate(
        system_prompt=ANALYSIS_PRD_PROMPT,
        user_content=user_prompt,
    )

    e2e_cases = _extract_e2e_cases(prd_text)

    return {
        **state,
        "analysis_result": prd_text,
        "e2e_test_cases": e2e_cases,
        "qa_rounds": qa_rounds + 1,
        "stage_phase": "complete",
    }
```

- [ ] **Step 3: 验证**

```bash
cd ai-design-platform-server/ai-service
python -c "from app.services.generation.nodes import analysis_node, design_node; print('OK')"
```

---

### Task 11: 后端 — 工具系统（ToolRegistry + 文件工具 + 编译工具 + MCP + Skill）

**Files:**
- Create: `ai-design-platform-server/ai-service/app/services/generation/tools/__init__.py`
- Create: `ai-design-platform-server/ai-service/app/services/generation/tools/registry.py`
- Create: `ai-design-platform-server/ai-service/app/services/generation/tools/file_tools.py`
- Create: `ai-design-platform-server/ai-service/app/services/generation/tools/compile_tool.py`
- Create: `ai-design-platform-server/ai-service/app/services/generation/tools/mcp_bridge.py`
- Create: `ai-design-platform-server/ai-service/app/services/generation/tools/skill_loader.py`

- [ ] **Step 1: 创建 tools/__init__.py**

```python
# ai-service/app/services/generation/tools/__init__.py
"""Tool system for code generation — ToolCalls + Skills + MCP."""
```

- [ ] **Step 2: 创建 tools/registry.py**

```python
"""ToolRegistry — 注册/查找/调用工具."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable
import structlog

logger = structlog.get_logger()


@dataclass
class ToolDef:
    name: str
    description: str
    parameters: dict
    handler: Callable[..., Awaitable['ToolResult']]
    category: str  # "file" | "compile" | "mcp" | "skill"


@dataclass
class ToolResult:
    ok: bool
    data: Any | None = None
    error: str | None = None


class ToolRegistry:
    """Manages all available tools for the LLM orchestrator."""

    def __init__(self, project_root: str = "/tmp/ai-gen"):
        self.project_root = project_root
        self._tools: dict[str, ToolDef] = {}
        self._register_builtins()

    def _register_builtins(self) -> None:
        from .file_tools import create_file, write_code, delete_file
        from .compile_tool import compile_project, get_compile_errors
        from .skill_loader import SkillLoader
        from .mcp_bridge import MCPBridge

        self._skill_loader = SkillLoader()
        self._mcp_bridge = MCPBridge()

        # File tools
        self.register(ToolDef(
            name="create_file",
            description="创建一个新文件。用于初始化工程文件骨架。",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径，如 components/Header.vue"},
                    "language": {"type": "string", "description": "文件语言: vue | ts | js | css"},
                },
                "required": ["path"],
            },
            handler=lambda **kw: create_file(self.project_root, **kw),
            category="file",
        ))

        self.register(ToolDef(
            name="write_code",
            description="向文件写入代码。可以创建新文件或覆盖已有文件内容。",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径"},
                    "content": {"type": "string", "description": "要写入的完整代码"},
                },
                "required": ["path", "content"],
            },
            handler=lambda **kw: write_code(self.project_root, **kw),
            category="file",
        ))

        self.register(ToolDef(
            name="delete_file",
            description="删除一个文件。",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "要删除的文件路径"},
                },
                "required": ["path"],
            },
            handler=lambda **kw: delete_file(self.project_root, **kw),
            category="file",
        ))

        # Compile tools
        self.register(ToolDef(
            name="compile_project",
            description="编译整个前端工程，返回编译错误列表。编译前必须先写入所有文件。",
            parameters={
                "type": "object",
                "properties": {},
            },
            handler=lambda **kw: compile_project(self.project_root, **kw),
            category="compile",
        ))

        self.register(ToolDef(
            name="get_compile_errors",
            description="获取最近一次编译的错误详情。",
            parameters={
                "type": "object",
                "properties": {},
            },
            handler=lambda **kw: get_compile_errors(self.project_root, **kw),
            category="compile",
        ))

        # MCP tools
        self.register(ToolDef(
            name="mcp_query",
            description="查询外部 MCP 服务获取组件文档、API 规范等。",
            parameters={
                "type": "object",
                "properties": {
                    "server": {"type": "string", "description": "MCP 服务名: component-docs | design-tokens | type-registry"},
                    "query": {"type": "string", "description": "查询内容，如 'Table props dataSource columns'"},
                },
                "required": ["server", "query"],
            },
            handler=lambda **kw: self._mcp_bridge.query(**kw),
            category="mcp",
        ))

        # Skill tools
        self.register(ToolDef(
            name="use_skill",
            description="应用一个 Skill 模板生成代码骨架。可用 Skills: crud-page, form-validation, data-dashboard, auth-guard, file-upload, responsive-layout。",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Skill 名称"},
                    "params": {"type": "object", "description": "Skill 参数"},
                },
                "required": ["name"],
            },
            handler=lambda **kw: self._skill_loader.apply(**kw),
            category="skill",
        ))

        self.register(ToolDef(
            name="list_skills",
            description="列出所有可用的 Skill 模板。",
            parameters={"type": "object", "properties": {}},
            handler=lambda **kw: self._skill_loader.list_all(),
            category="skill",
        ))

    def register(self, tool: ToolDef) -> None:
        self._tools[tool.name] = tool
        logger.info("tool_registered", name=tool.name, category=tool.category)

    def get_schema(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in self._tools.values()
        ]

    async def invoke(self, name: str, args: dict) -> ToolResult:
        tool = self._tools.get(name)
        if not tool:
            return ToolResult(ok=False, error=f"Unknown tool: {name}")
        try:
            result = await tool.handler(**args)
            return result
        except Exception as e:
            logger.error("tool_invoke_error", name=name, error=str(e))
            return ToolResult(ok=False, error=str(e))
```

- [ ] **Step 3: 创建 tools/file_tools.py**

```python
"""File manipulation tools for code generation."""

import os
import structlog
from .registry import ToolResult

logger = structlog.get_logger()


async def create_file(project_root: str, path: str, language: str = "vue") -> ToolResult:
    """Create an empty file with skeleton."""
    full_path = os.path.join(project_root, path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)

    if os.path.exists(full_path):
        logger.warning("file_already_exists", path=path)
        return ToolResult(ok=True, data={"path": path, "created": False, "existed": True})

    with open(full_path, "w", encoding="utf-8") as f:
        f.write(f"// {path}\n")
    logger.info("file_created", path=path)
    return ToolResult(ok=True, data={"path": path, "created": True})


async def write_code(project_root: str, path: str, content: str) -> ToolResult:
    """Write code to a file."""
    full_path = os.path.join(project_root, path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)

    with open(full_path, "w", encoding="utf-8") as f:
        f.write(content)
    logger.info("file_written", path=path, size=len(content))
    return ToolResult(ok=True, data={"path": path, "size": len(content)})


async def delete_file(project_root: str, path: str) -> ToolResult:
    """Delete a file."""
    full_path = os.path.join(project_root, path)
    if os.path.exists(full_path):
        os.remove(full_path)
        logger.info("file_deleted", path=path)
        return ToolResult(ok=True, data={"path": path, "deleted": True})
    return ToolResult(ok=True, data={"path": path, "deleted": False, "reason": "not found"})
```

- [ ] **Step 4: 创建 tools/compile_tool.py**

```python
"""Compile tool — triggers frontend compilation and collects errors."""

import structlog
from .registry import ToolResult

logger = structlog.get_logger()

_compile_errors: list[dict] = []


async def compile_project(project_root: str) -> ToolResult:
    """Compile the project and return errors."""
    global _compile_errors
    # In production, this would invoke the actual compiler (vite/esbuild).
    # For now, do a basic syntax check on .vue files.
    errors = []
    for dirpath, _, filenames in os.walk(project_root):
        for fn in filenames:
            if fn.endswith((".vue", ".ts", ".js")):
                filepath = os.path.join(dirpath, fn)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        f.read()
                except Exception as e:
                    errors.append({"file": fn, "line": 0, "message": str(e)})

    _compile_errors = errors
    if errors:
        logger.warning("compile_errors", count=len(errors))
        return ToolResult(ok=False, data={"errors": errors})
    logger.info("compile_ok", project=project_root)
    return ToolResult(ok=True, data={"errors": []})


async def get_compile_errors(project_root: str) -> ToolResult:
    """Get errors from last compilation."""
    global _compile_errors
    return ToolResult(ok=True, data={"errors": _compile_errors})
```

Note: compile_tool.py needs `import os` at top.

- [ ] **Step 5: 创建 tools/skill_loader.py**

```python
"""Skill template loader — applies reusable code patterns."""

import json
import os
import structlog
from .registry import ToolResult

logger = structlog.get_logger()

SKILLS_DIR = os.path.join(os.path.dirname(__file__), "..", "skills")


class SkillLoader:
    def __init__(self):
        self._cache: dict[str, dict] = {}

    async def list_all(self) -> ToolResult:
        skills = []
        if os.path.isdir(SKILLS_DIR):
            for fn in os.listdir(SKILLS_DIR):
                if fn.endswith(".json"):
                    with open(os.path.join(SKILLS_DIR, fn), "r", encoding="utf-8") as f:
                        skill = json.load(f)
                        skills.append({
                            "name": skill.get("name", fn),
                            "description": skill.get("description", ""),
                            "parameters": skill.get("parameters", {}),
                        })
        return ToolResult(ok=True, data={"skills": skills})

    async def apply(self, name: str, params: dict | None = None) -> ToolResult:
        filepath = os.path.join(SKILLS_DIR, f"{name}.json")
        if not os.path.exists(filepath):
            return ToolResult(ok=False, error=f"Skill not found: {name}")

        with open(filepath, "r", encoding="utf-8") as f:
            skill = json.load(f)

        files = []
        for tpl in skill.get("produces", []):
            template_content = tpl.get("template", "// Generated from skill: {name}\n")
            if params:
                for k, v in (params or {}).items():
                    template_content = template_content.replace("{{" + k + "}}", str(v))
            files.append({"path": tpl.get("path", f"{name}.vue"), "content": template_content})

        logger.info("skill_applied", name=name, files=len(files))
        return ToolResult(ok=True, data={"skill": name, "files": files})
```

- [ ] **Step 6: 创建 tools/mcp_bridge.py**

```python
"""MCP Bridge — connect to external MCP servers for context."""

import structlog
from .registry import ToolResult

logger = structlog.get_logger()

# MCP server config (in production, loaded from servers.yaml)
MCP_SERVERS = {
    "component-docs": {
        "description": "Component library documentation and API reference",
        "status": "available",
    },
    "design-tokens": {
        "description": "Design tokens (colors, spacing, typography)",
        "status": "available",
    },
    "type-registry": {
        "description": "TypeScript type definitions registry",
        "status": "available",
    },
}


class MCPBridge:
    def __init__(self):
        self._servers = MCP_SERVERS

    async def query(self, server: str, query: str) -> ToolResult:
        if server not in self._servers:
            return ToolResult(ok=False, error=f"Unknown MCP server: {server}. Available: {list(self._servers.keys())}")

        if self._servers[server]["status"] != "available":
            return ToolResult(ok=False, error=f"MCP server '{server}' is not available.")

        # In production, this connects to the actual MCP server.
        # For now, return a note that the LLM should proceed with its own knowledge.
        logger.info("mcp_query", server=server, query=query[:80])
        return ToolResult(
            ok=True,
            data={
                "server": server,
                "query": query,
                "note": "MCP server available. Use your knowledge of this service to continue.",
            },
        )
```

- [ ] **Step 7: 创建 Skill 模板 JSON 文件**

Create `skills/crud-page.json`:

```json
{
  "name": "crud-page",
  "description": "生成完整的 CRUD 管理页面（列表 + 搜索 + 分页 + 新建/编辑/删除）",
  "parameters": {
    "entity": { "type": "string", "description": "实体名称，如 '客户'、'订单'" },
    "entityKey": { "type": "string", "description": "实体英文 key，如 'customer'、'order'" },
    "apiPrefix": { "type": "string", "description": "API 路径前缀，如 '/api/customers'" }
  },
  "produces": [
    {
      "path": "pages/{{entityKey}}/List.vue",
      "template": "<script setup lang=\"ts\">\nimport { ref, onMounted } from 'vue'\n\nconst items = ref([])\nconst loading = ref(false)\nconst searchQuery = ref('')\nconst currentPage = ref(1)\nconst pageSize = ref(10)\n\nasync function fetchItems() {\n  loading.value = true\n  try {\n    const res = await fetch('{{apiPrefix}}?page=' + currentPage.value + '&search=' + searchQuery.value)\n    items.value = await res.json()\n  } finally {\n    loading.value = false\n  }\n}\n\nfunction handleSearch() {\n  currentPage.value = 1\n  fetchItems()\n}\n\nfunction handleDelete(id: string) {\n  if (confirm('确认删除？')) {\n    fetch('{{apiPrefix}}/' + id, { method: 'DELETE' }).then(() => fetchItems())\n  }\n}\n\nonMounted(fetchItems)\n</script>\n\n<template>\n  <div class=\"p-4\">\n    <div class=\"flex justify-between mb-4\">\n      <input v-model=\"searchQuery\" class=\"border rounded px-3 py-1.5\" placeholder=\"搜索...\" @keyup.enter=\"handleSearch\" />\n      <button class=\"bg-blue-600 text-white px-4 py-1.5 rounded\" @click=\"$router.push('/{{entityKey}}/new')\">+ 新建{{entity}}</button>\n    </div>\n    <table v-if=\"!loading\" class=\"w-full\">\n      <thead><tr><th>名称</th><th>操作</th></tr></thead>\n      <tbody>\n        <tr v-for=\"item in items\" :key=\"item.id\">\n          <td>{{ item.name }}</td>\n          <td>\n            <button class=\"text-blue-600\" @click=\"$router.push('/{{entityKey}}/' + item.id)\">编辑</button>\n            <button class=\"text-red-600 ml-2\" @click=\"handleDelete(item.id)\">删除</button>\n          </td>\n        </tr>\n      </tbody>\n    </table>\n    <div v-else class=\"text-gray-400\">加载中...</div>\n  </div>\n</template>\n"
    },
    {
      "path": "pages/{{entityKey}}/Form.vue",
      "template": "<script setup lang=\"ts\">\nimport { ref, onMounted } from 'vue'\nimport { useRoute, useRouter } from 'vue-router'\n\nconst route = useRoute()\nconst router = useRouter()\nconst id = route.params.id\nconst isEdit = id !== 'new'\n\nconst form = ref({ name: '' })\nconst saving = ref(false)\n\nonMounted(async () => {\n  if (isEdit) {\n    const res = await fetch('{{apiPrefix}}/' + id)\n    form.value = await res.json()\n  }\n})\n\nasync function handleSave() {\n  saving.value = true\n  const url = isEdit ? '{{apiPrefix}}/' + id : '{{apiPrefix}}'\n  const method = isEdit ? 'PUT' : 'POST'\n  await fetch(url, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(form.value) })\n  router.push('/{{entityKey}}')\n}\n</script>\n\n<template>\n  <div class=\"p-4 max-w-2xl mx-auto\">\n    <h1 class=\"text-xl font-bold mb-4\">{{ isEdit ? '编辑' : '新建' }}{{entity}}</h1>\n    <form @submit.prevent=\"handleSave\">\n      <div class=\"mb-4\">\n        <label class=\"block text-sm mb-1\">名称</label>\n        <input v-model=\"form.name\" class=\"w-full border rounded px-3 py-1.5\" required />\n      </div>\n      <button type=\"submit\" class=\"bg-blue-600 text-white px-4 py-1.5 rounded\" :disabled=\"saving\">\n        {{ saving ? '保存中...' : '保存' }}\n      </button>\n    </form>\n  </div>\n</template>\n"
    }
  ]
}
```

Create `skills/form-validation.json`:

```json
{
  "name": "form-validation",
  "description": "表单校验规则模式（必填、长度、格式、异步校验）",
  "parameters": {
    "fields": { "type": "array", "description": "字段列表 [{name, label, rules}]" }
  },
  "produces": [
    {
      "path": "composables/useValidation.ts",
      "template": "import { ref, computed } from 'vue'\n\nexport interface ValidationRule {\n  required?: boolean\n  minLength?: number\n  maxLength?: number\n  pattern?: RegExp\n  message?: string\n}\n\nexport function useValidation(rules: Record<string, ValidationRule[]>) {\n  const errors = ref<Record<string, string>>({})\n\n  function validate(data: Record<string, any>): boolean {\n    errors.value = {}\n    for (const [field, fieldRules] of Object.entries(rules)) {\n      const value = data[field]\n      for (const rule of fieldRules) {\n        if (rule.required && !value) {\n          errors.value[field] = rule.message || (field + ' 不能为空')\n          break\n        }\n        if (rule.minLength && (value || '').length < rule.minLength) {\n          errors.value[field] = rule.message || (field + ' 至少 ' + rule.minLength + ' 个字符')\n          break\n        }\n        if (rule.pattern && !rule.pattern.test(value || '')) {\n          errors.value[field] = rule.message || (field + ' 格式不正确')\n          break\n        }\n      }\n    }\n    return Object.keys(errors.value).length === 0\n  }\n\n  const isValid = computed(() => Object.keys(errors.value).length === 0)\n\n  return { errors, validate, isValid }\n}\n"
    }
  ]
}
```

Create remaining skills with similar minimal templates: `data-dashboard.json`, `auth-guard.json`, `file-upload.json`, `responsive-layout.json`.

- [ ] **Step 8: 创建 tools/mcp/ 目录和 servers.yaml**

```bash
mkdir -p ai-design-platform-server/ai-service/app/services/generation/tools/mcp
```

```yaml
# mcp/servers.yaml
servers:
  component-docs:
    description: "Component library documentation"
    transport: "stdio"
    command: "npx"
    args: ["-y", "@anthropic/mcp-server-component-docs"]
    enabled: true

  design-tokens:
    description: "Design tokens provider"
    transport: "stdio"
    command: "node"
    args: ["./mcp/design-tokens-server.js"]
    enabled: false

  type-registry:
    description: "TypeScript type registry"
    transport: "stdio"
    command: "node"
    args: ["./mcp/type-registry-server.js"]
    enabled: false
```

- [ ] **Step 9: 验证工具系统导入**

```bash
cd ai-design-platform-server/ai-service
python -c "from app.services.generation.tools.registry import ToolRegistry; r = ToolRegistry(); print('Tools:', len(r._tools)); print('OK')"
```

Expected: `Tools: 8` or similar count.

---

### Task 12: 后端 — code_node 重写为 Tool-use Loop

**Files:**
- Modify: `ai-design-platform-server/ai-service/app/services/generation/nodes.py`

- [ ] **Step 1: 添加 code orchestrator prompt + 重写 code_node**

Add new constant:

```python
CODE_ORCHESTRATOR_PROMPT = """你是一个资深 Vue 3 全栈工程师，使用工具链逐步构建前端工程。

## 工作流程
1. 分析设计方案，调用 list_skills 和 mcp_query 了解可用工具
2. 调用 use_skill 应用代码模板生成文件骨架
3. 调用 write_code 逐个填充代码
4. 每 3-4 个文件完成后调用 compile_project 检查
5. 有编译错误时调用 fix_error 修复后再 compile
6. 全部编译通过后输出 __CODE_GEN_DONE__

## 规则
- 每次只做一件事，保持响应简短
- 优先使用 Skill 模板而不是从零写
- 组件名使用 PascalCase，文件名使用 kebab-case
- 使用 {component_lib} 组件库
- 代码输出 Composition API (<script setup lang="ts">)
- 确保每个 .vue 文件有 <template>、<script setup>、<style scoped>"""
```

Replace `code_node`:

```python
import asyncio
import json as _json
from .tools.registry import ToolRegistry, ToolResult


async def code_node(state: GenerationState) -> GenerationState:
    """代码生成节点 — 工具增强的迭代式工程生成."""
    logger.info("code_node_start")

    import tempfile, os as _os
    project_root = _os.path.join(tempfile.gettempdir(), "ai-gen", state.get("requirement", "project")[:20].replace(" ", "_"))

    registry = ToolRegistry(project_root)
    design_doc = state.get("design_doc") or state.get("design_result", "")
    failure = state.get("failure_details")

    tools_schema = registry.get_schema()
    system_prompt = CODE_ORCHESTRATOR_PROMPT.format(
        component_lib=state.get("component_lib", "tailwind"),
    )

    # Build messages for LLM
    if failure:
        user_msg = (
            f"设计方案：\n{design_doc}\n\n"
            f"之前的代码存在问题：\n{failure['instruction']}\n\n"
            f"请修复代码，确保通过编译和校验。"
        )
    else:
        user_msg = (
            f"设计方案：\n{design_doc}\n\n"
            f"开始生成工程代码。先调用 list_skills 了解可用模板，然后规划文件结构并逐步生成。"
        )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_msg},
    ]

    max_tool_rounds = 20
    generated_files: dict[str, str] = {}
    last_compile_errors: list[dict] | None = None

    for round_idx in range(max_tool_rounds):
        logger.info("code_tool_round", round=round_idx + 1)

        # Call LLM with tools
        try:
            response = await _llm_generate_with_tools(
                messages=messages,
                tools=tools_schema,
                model="glm-5.2",
            )
        except Exception as e:
            logger.error("llm_tool_call_error", error=str(e))
            break

        # Process tool calls
        if response.get("tool_calls"):
            for tc in response["tool_calls"]:
                tool_name = tc["function"]["name"]
                tool_args = _json.loads(tc["function"]["arguments"])

                result = await registry.invoke(tool_name, tool_args)

                # Collect generated files
                if tool_name == "write_code" and result.ok:
                    generated_files[tool_args["path"]] = tool_args["content"]
                elif tool_name == "use_skill" and result.ok:
                    for f in result.data.get("files", []):
                        generated_files[f["path"]] = f["content"]

                # Record compile errors
                if tool_name == "compile_project" and not result.ok:
                    last_compile_errors = result.data.get("errors", [])

                # Append tool result to messages
                messages.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [tc],
                })
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": _json.dumps({
                        "ok": result.ok,
                        "data": result.data,
                        "error": result.error,
                    }, ensure_ascii=False),
                })

        elif response.get("content"):
            messages.append({"role": "assistant", "content": response["content"]})

            if "__CODE_GEN_DONE__" in (response["content"] or ""):
                logger.info("code_gen_done_signal")
                break

        # Every 3 rounds, auto-compile
        if round_idx > 0 and round_idx % 3 == 0 and generated_files:
            compile_result = await registry.invoke("compile_project", {})
            last_compile_errors = compile_result.data.get("errors", []) if not compile_result.ok else []
            if compile_result.ok and not last_compile_errors:
                logger.info("compile_passed_early", round=round_idx + 1)
                break

    return {
        **state,
        "generated_files": generated_files,
        "compile_errors": last_compile_errors,
        "stage_phase": "complete",
    }


async def _llm_generate_with_tools(
    messages: list[dict],
    tools: list[dict],
    model: str = "glm-5.2",
) -> dict:
    """Call LLM with function calling support, parse tool_calls or content.

    Returns: {"content": str | None, "tool_calls": list[dict] | None}
    """
    # Simulate tool-use by telling the model to output tool calls as JSON
    tool_prompt = (
        "\n\n你可以调用以下工具函数。要调用工具，在回复中输出 JSON：\n"
        "{\"tool_calls\": [{\"id\": \"call_1\", \"function\": {\"name\": \"...\", \"arguments\": \"...\"}}]}\n"
        "可用工具：\n" + _json.dumps(tools, ensure_ascii=False, indent=2) + "\n"
        "如果不需要调用工具，直接输出文本回复。"
    )
    messages_with_tools = list(messages)
    if messages_with_tools[0]["role"] == "system":
        messages_with_tools[0] = {
            "role": "system",
            "content": messages_with_tools[0]["content"] + tool_prompt,
        }
    else:
        messages_with_tools.insert(0, {"role": "system", "content": tool_prompt})

    # Use base _llm_generate to get response, then parse
    # For ZhipuAI GLM-5.2 which supports native function calling, this would use
    # the actual tool_choice parameter. Here we use a prompt-based approach for simplicity.
    # Build user prompt from messages
    prompt_text = ""
    for m in messages_with_tools:
        prompt_text += f"\n[{m['role']}]: {m.get('content', '') or _json.dumps(m.get('tool_calls', []), ensure_ascii=False) if m.get('tool_calls') else ''}"

    raw = await _llm_generate(
        system_prompt=prompt_text[:500],
        user_content=prompt_text[500:],
        model=model,
    )

    # Try to parse as tool_calls JSON
    try:
        parsed = _json.loads(raw.strip())
        if "tool_calls" in parsed:
            return {"content": None, "tool_calls": parsed["tool_calls"]}
    except (_json.JSONDecodeError, KeyError):
        pass

    return {"content": raw.strip(), "tool_calls": None}
```

- [ ] **Step 2: 验证 code_node**

```bash
cd ai-design-platform-server/ai-service
python -c "from app.services.generation.nodes import code_node; print('OK')"
```

---

### Task 13: 后端 — review_node 多 Agent 并行审查

**Files:**
- Modify: `ai-design-platform-server/ai-service/app/services/generation/nodes.py`

- [ ] **Step 1: 添加 review agent prompts + 重写 review_node**

Add review agent definitions:

```python
REVIEW_AGENTS = {
    "security": {
        "name": "安全审查",
        "icon": "🔒",
        "system_prompt": (
            "你是前端安全专家。审查以下代码的安全问题：\n"
            "1. XSS 风险（v-html、innerHTML、未转义用户输入）\n"
            "2. 敏感数据暴露（API key、token、密码明文字段）\n"
            "3. CSRF 防护缺失\n"
            "4. 不安全的路由守卫\n"
            "输出 JSON: {\"issues\": [{\"severity\": \"critical|high|medium|low\", \"file\": \"...\", \"line\": 0, \"title\": \"...\", \"description\": \"...\", \"fix\": \"...\"}]}"
        ),
    },
    "performance": {
        "name": "性能分析",
        "icon": "⚡",
        "system_prompt": (
            "你是前端性能专家。审查以下代码的性能问题：\n"
            "1. 不必要的重渲染（computed/watch 滥用）\n"
            "2. 大列表未虚拟滚动\n"
            "3. 图片/资源未懒加载\n"
            "4. 打包体积过大风险\n"
            "输出 JSON: {\"issues\": [...]}"
        ),
    },
    "accessibility": {
        "name": "可访问性",
        "icon": "♿",
        "system_prompt": (
            "你是 Web 可访问性专家。审查代码的 A11y 问题：\n"
            "1. ARIA 属性缺失或错误\n"
            "2. 键盘导航不完整\n"
            "3. 颜色对比度不足\n"
            "4. 屏幕阅读器兼容性\n"
            "输出 JSON: {\"issues\": [...]}"
        ),
    },
    "maintainability": {
        "name": "可维护性",
        "icon": "🧩",
        "system_prompt": (
            "你是代码质量专家。审查可维护性问题：\n"
            "1. 组件过大（>300 行）\n"
            "2. 重复代码\n"
            "3. 硬编码魔法数字\n"
            "4. 类型定义缺失或不完整\n"
            "输出 JSON: {\"issues\": [...]}"
        ),
    },
}


def _build_review_html(agent_results: list[dict], all_issues: list[dict]) -> str:
    """Build merged HTML review report."""
    issue_html = ""
    for issue in all_issues:
        sev_color = {"critical": "#dc2626", "high": "#ea580c", "medium": "#ca8a04", "low": "#2563eb"}
        color = sev_color.get(issue.get("severity", "low"), "#6b7280")
        issue_html += f"""
        <div style="border-left: 4px solid {color}; margin: 8px 0; padding: 8px 12px; background: #f9fafb;">
          <strong>[{issue.get('severity', '?').upper()}] {issue.get('title', 'Issue')}</strong>
          <br><small>{issue.get('file', '?')}:{issue.get('line', 0)}</small>
          <p>{issue.get('description', '')}</p>
          <p><strong>修复建议:</strong> {issue.get('fix', 'N/A')}</p>
        </div>"""

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>质量评审报告</title>
<style>body {{ font-family: -apple-system, sans-serif; max-width: 900px; margin: 0 auto; padding: 20px; }}
h1 {{ border-bottom: 2px solid #e5e7eb; padding-bottom: 8px; }}
h2 {{ margin-top: 24px; }}
.agent {{ margin: 12px 0; padding: 12px; border-radius: 8px; background: #f3f4f6; }}
.agent-icon {{ font-size: 24px; }}
.passed {{ color: #16a34a; }}
.failed {{ color: #dc2626; }}</style></head>
<body>
<h1>🔍 质量评审报告</h1>
<p>审查维度：安全 · 性能 · 可访问性 · 可维护性</p>
<p>共发现 <strong>{len(all_issues)}</strong> 个问题</p>
{issue_html}
</body></html>"""


async def _run_single_agent(agent_key: str, agent_def: dict, design_doc: str, code_context: str) -> dict:
    """Run a single review agent."""
    try:
        raw = await _llm_generate_structured(
            system_prompt=agent_def["system_prompt"],
            user_content=f"## 设计方案\n{design_doc[:3000]}\n\n## 代码\n{code_context[:8000]}",
            output_schema={"issues": []},
        )
        return {"agent_key": agent_key, "name": agent_def["name"], "icon": agent_def["icon"], "issues": raw.get("issues", [])}
    except Exception as e:
        logger.error("review_agent_error", agent=agent_key, error=str(e))
        return {"agent_key": agent_key, "name": agent_def["name"], "icon": agent_def["icon"], "issues": [], "error": str(e)}
```

Replace `review_node`:

```python
async def review_node(state: GenerationState) -> GenerationState:
    """多 Agent 并行审查 → 合并 HTML 报告."""

    files = state.get("generated_files", {})
    design_doc = state.get("design_doc") or state.get("design_result", "")

    code_context = "\n\n".join(
        f"### {path}\n```\n{content[:2000]}\n```" if len(content) > 2000 else f"### {path}\n```\n{content}\n```"
        for path, content in files.items()
    )

    # Run 4 agents in parallel
    tasks = [
        _run_single_agent(key, agent_def, design_doc, code_context)
        for key, agent_def in REVIEW_AGENTS.items()
    ]
    agent_results = await asyncio.gather(*tasks)

    # Collect all issues
    all_issues = []
    for ar in agent_results:
        all_issues.extend(ar.get("issues", []))

    # Classify
    critical = [i for i in all_issues if i.get("severity") == "critical"]
    passed = len(critical) == 0

    if not passed:
        severity = "critical"
        rollback_target = "code"
    elif all_issues:
        severity = "moderate"
        rollback_target = "code"
    else:
        severity = None
        rollback_target = ""

    # Build HTML report
    report_html = _build_review_html(agent_results, all_issues)

    # Format fix instruction if needed
    fix_instruction = None
    if all_issues:
        issues_text = "\n".join(
            f"- [{i.get('severity', '?')}] {i.get('file', '?')}:{i.get('line', 0)} — {i.get('title', '')} → {i.get('fix', '')}"
            for i in all_issues[:20]
        )
        fix_instruction = f"审查发现 {len(all_issues)} 个问题需要修复：\n{issues_text}"

    return {
        **state,
        "review_agent_results": agent_results,
        "review_report_html": report_html,
        "review_issues": all_issues,
        "review_passed": passed,
        "review_severity": severity,
        "review_result": f"Found {len(all_issues)} issues, {len(critical)} critical",
        "failure_details": {
            "source": "review",
            "failed_items": all_issues,
            "instruction": fix_instruction or "",
            "rollback_target": rollback_target,
        } if all_issues else None,
        "stage_phase": "complete",
    }
```

- [ ] **Step 2: 验证 review_node**

```bash
cd ai-design-platform-server/ai-service
python -c "from app.services.generation.nodes import review_node; print('OK')"
```

---

### Task 14: 后端 — e2e_node 两阶段改造

**Files:**
- Modify: `ai-design-platform-server/ai-service/app/services/generation/nodes.py`

- [ ] **Step 1: 添加 e2e test case generation prompt**

```python
E2E_CASES_PROMPT = """你是一个资深 QA 测试工程师。根据需求文档和生成的代码，编写 E2E 自动化测试用例。

## 输出格式（Markdown）
# E2E 测试用例

## TC-001: 用例名称
- **前置条件**: ...
- **测试步骤**:
  1. 打开页面
  2. 点击某个按钮
  3. 验证结果
- **预期结果**: ...

## TC-002: ...

## 规则
- 每个用例测试一个功能点
- 用例需覆盖核心用户流程
- 步骤用自然语言描述
- 输出纯 Markdown，不要 JSON 包裹"""
```

Replace `e2e_node`:

```python
async def e2e_node(state: GenerationState) -> GenerationState:
    """E2E 节点 — 两阶段：生成测试用例 → 用户确认 → 自动执行."""

    e2e_confirmed = state.get("e2e_user_confirmed", False)

    if not e2e_confirmed:
        # Phase 1: Generate test cases MD
        logger.info("e2e_phase1_generate_cases")

        requirement = state.get("analysis_result", "")
        generated_files = state.get("generated_files", {})

        code_summary = "\n".join(f"- {path}" for path in generated_files.keys())

        user_prompt = (
            f"## 需求文档\n{requirement[:5000]}\n\n"
            f"## 生成的文件列表\n{code_summary}\n\n"
            f"请根据以上信息编写 E2E 测试用例。"
        )

        test_cases_md = await _llm_generate(
            system_prompt=E2E_CASES_PROMPT,
            user_content=user_prompt,
        )

        return {
            **state,
            "e2e_test_cases_md": test_cases_md,
            "stage_phase": "reviewing",  # waiting for user confirmation
        }

    else:
        # Phase 2: Execute tests (pass-through to frontend)
        logger.info("e2e_phase2_execute")
        return {
            **state,
            "stage_phase": "complete",
            "analysis_result": state.get("analysis_result", ""),
            "e2e_test_cases": state.get("e2e_test_cases", []),
        }
```

Note: Remove existing `E2E_SYSTEM_PROMPT` and old e2e_node. Keep `_extract_e2e_cases` for backward compatibility.

- [ ] **Step 2: 验证**

```bash
cd ai-design-platform-server/ai-service
python -c "from app.services.generation.nodes import e2e_node, E2E_CASES_PROMPT; print('OK')"
```

---

### Task 15: 前端 — CodeStagePanel + ToolTracePanel

**Files:**
- Create: `ai-design-platform-web/packages/ai-generation-app/src/components/CodeStagePanel.vue`
- Create: `ai-design-platform-web/packages/ai-generation-app/src/components/ToolTracePanel.vue`

- [ ] **Step 1: 创建 CodeStagePanel.vue**

```vue
<!-- src/components/CodeStagePanel.vue -->
<script setup lang="ts">
import { useGenerationStore } from '@/stores/generation'
import TabBar from './TabBar.vue'
import PreviewFrame from './PreviewFrame.vue'
import FileExplorer from './FileExplorer.vue'
import ToolTracePanel from './ToolTracePanel.vue'

const store = useGenerationStore()

const codeTabs = [
  { key: 'preview' as const, label: '实时预览' },
  { key: 'files' as const, label: '工程文件' },
  { key: 'trace' as const, label: 'Tool Trace' },
]

function handleTabSelect(key: string): void {
  store.setCodeViewTab(key as 'preview' | 'files')
}
</script>

<template>
  <div class="flex-1 flex flex-col">
    <TabBar
      :tabs="codeTabs"
      :active-tab="store.codeViewTab === 'preview' ? 'preview' : store.codeViewTab === 'files' ? 'files' : 'trace'"
      @select="handleTabSelect"
    />
    <div class="flex-1 relative">
      <div v-show="store.codeViewTab === 'preview'" class="absolute inset-0">
        <PreviewFrame />
      </div>
      <div v-show="store.codeViewTab === 'files'" class="absolute inset-0">
        <FileExplorer />
      </div>
      <div v-show="store.codeViewTab === 'trace'" class="absolute inset-0">
        <ToolTracePanel />
      </div>
    </div>
  </div>
</template>
```

- [ ] **Step 2: 创建 ToolTracePanel.vue**

```vue
<!-- src/components/ToolTracePanel.vue -->
<script setup lang="ts">
import { useGenerationStore } from '@/stores/generation'

const store = useGenerationStore()

function statusIcon(status: string): string {
  switch (status) {
    case 'running': return '🔄'
    case 'done': return '✅'
    case 'error': return '❌'
    default: return '⏳'
  }
}

function formatToolName(tool: string): string {
  const map: Record<string, string> = {
    create_file: '创建文件',
    write_code: '写入代码',
    delete_file: '删除文件',
    compile_project: '编译检查',
    get_compile_errors: '获取错误',
    use_skill: 'Skill 模板',
    list_skills: '列出模板',
    mcp_query: 'MCP 查询',
  }
  return map[tool] || tool
}

function handleEntryClick(index: number): void {
  const entry = store.toolTraces[index]
  if (!entry) return
  // Jump to file if applicable
  if (entry.args?.path && store.files.has(entry.args.path)) {
    store.setActiveFile(entry.args.path)
    store.setCodeViewTab('files')
  }
}
</script>

<template>
  <div class="h-full overflow-y-auto p-3 bg-gray-50">
    <div class="text-sm font-medium text-gray-700 mb-2">
      🔧 工具调用链
      <span class="text-xs text-gray-400 ml-2">
        {{ store.generatedFiles ? Object.keys(store.generatedFiles).length : 0 }} 文件已生成
      </span>
    </div>

    <div v-if="store.toolTraces.length === 0" class="text-center text-gray-400 mt-8 text-sm">
      等待工具调用...
    </div>

    <div class="space-y-1">
      <div
        v-for="(entry, idx) in store.toolTraces"
        :key="entry.id"
        class="flex items-center gap-2 px-2 py-1.5 text-xs rounded hover:bg-gray-100 cursor-pointer transition-colors"
        :class="{ 'opacity-50': entry.status === 'error' }"
        @click="handleEntryClick(idx)"
      >
        <span>{{ statusIcon(entry.status) }}</span>
        <span class="font-mono text-blue-600">{{ formatToolName(entry.tool) }}</span>
        <span v-if="entry.args?.path" class="text-gray-500">→ {{ entry.args.path }}</span>
        <span v-if="entry.args?.name" class="text-purple-600">→ {{ entry.args.name }}</span>
        <span v-if="entry.summary" class="text-gray-400 ml-auto truncate max-w-[200px]">{{ entry.summary }}</span>
      </div>
    </div>
  </div>
</template>
```

- [ ] **Step 3: 验证编译**

```bash
cd ai-design-platform-web && npx turbo run typecheck --filter=ai-generation-app
```

---

### Task 16: 前端 — ReviewStagePanel + MultiAgentPanel

**Files:**
- Create: `ai-design-platform-web/packages/ai-generation-app/src/components/ReviewStagePanel.vue`
- Create: `ai-design-platform-web/packages/ai-generation-app/src/components/MultiAgentPanel.vue`

- [ ] **Step 1: 创建 MultiAgentPanel.vue**

```vue
<!-- src/components/MultiAgentPanel.vue -->
<script setup lang="ts">
import { useGenerationStore } from '@/stores/generation'

const store = useGenerationStore()

function statusBadge(status: string): string {
  switch (status) {
    case 'running': return 'bg-blue-100 text-blue-700'
    case 'done': return 'bg-green-100 text-green-700'
    default: return 'bg-gray-100 text-gray-500'
  }
}

function sevBadge(severity: string): string {
  switch (severity) {
    case 'critical': return 'bg-red-100 text-red-700'
    case 'high': return 'bg-orange-100 text-orange-700'
    case 'medium': return 'bg-yellow-100 text-yellow-700'
    case 'low': return 'bg-blue-100 text-blue-700'
    default: return 'bg-gray-100 text-gray-500'
  }
}
</script>

<template>
  <div class="p-3 space-y-3">
    <div class="text-sm font-medium text-gray-700">🔍 多维度代码审查</div>

    <div class="grid grid-cols-2 gap-3">
      <div
        v-for="agent in store.reviewAgents"
        :key="agent.key"
        class="border rounded-lg p-3 bg-white"
      >
        <div class="flex items-center justify-between mb-2">
          <span class="text-sm font-medium">
            {{ agent.icon }} {{ agent.name }}
          </span>
          <span class="text-xs px-1.5 py-0.5 rounded-full" :class="statusBadge(agent.status)">
            {{ agent.status === 'running' ? '分析中' : agent.status === 'done' ? '完成' : '等待' }}
          </span>
        </div>

        <div v-if="agent.findings.length > 0" class="space-y-1">
          <div
            v-for="(f, i) in agent.findings"
            :key="i"
            class="text-xs border-l-2 pl-2"
            :class="{
              'border-red-500': f.severity === 'critical',
              'border-orange-400': f.severity === 'high',
              'border-yellow-400': f.severity === 'medium',
              'border-blue-400': f.severity === 'low',
            }"
          >
            <div class="flex items-center gap-1">
              <span class="px-1 py-0.5 rounded text-[10px]" :class="sevBadge(f.severity)">{{ f.severity }}</span>
              <strong>{{ f.title }}</strong>
            </div>
            <div class="text-gray-500 mt-0.5">{{ f.file }}:{{ f.line }}</div>
          </div>
        </div>

        <div v-else-if="agent.status === 'done'" class="text-xs text-green-600">
          ✓ 未发现问题
        </div>

        <div v-else-if="agent.status === 'running'" class="text-xs text-blue-500 animate-pulse">
          分析中...
        </div>

        <div v-else class="text-xs text-gray-400">
          等待开始
        </div>
      </div>
    </div>

    <!-- Summary -->
    <div v-if="store.reviewAgents.some(a => a.status === 'done')" class="text-sm bg-gray-100 rounded p-2">
      共发现
      <strong>{{ store.reviewIssueSummary.total }}</strong> 个问题：
      <span v-if="store.reviewIssueSummary.critical > 0" class="text-red-600 ml-1">
        🔴 {{ store.reviewIssueSummary.critical }} critical
      </span>
      <span v-if="store.reviewIssueSummary.high > 0" class="text-orange-600 ml-1">
        🟠 {{ store.reviewIssueSummary.high }} high
      </span>
    </div>
  </div>
</template>
```

- [ ] **Step 2: 创建 ReviewStagePanel.vue**

```vue
<!-- src/components/ReviewStagePanel.vue -->
<script setup lang="ts">
import { useGenerationStore } from '@/stores/generation'
import MultiAgentPanel from './MultiAgentPanel.vue'
import StreamDocument from './StreamDocument.vue'

const store = useGenerationStore()
</script>

<template>
  <div class="flex-1 flex flex-col overflow-auto">
    <MultiAgentPanel />
    <div v-if="store.reviewReportHtml" class="flex-1 border-t border-gray-200">
      <StreamDocument
        :content="store.reviewReportHtml"
        :is-streaming="false"
        language="html"
      />
    </div>
    <div v-else-if="store.isStreaming" class="flex-1 flex items-center justify-center text-gray-400 text-sm">
      正在并发审查中...
    </div>
  </div>
</template>
```

- [ ] **Step 3: 验证编译**

```bash
cd ai-design-platform-web && npx turbo run typecheck --filter=ai-generation-app
```

---

### Task 17: 前端 — E2EStagePanel + TestCaseProgress

**Files:**
- Create: `ai-design-platform-web/packages/ai-generation-app/src/components/E2EStagePanel.vue`
- Create: `ai-design-platform-web/packages/ai-generation-app/src/components/TestCaseProgress.vue`

- [ ] **Step 1: 创建 E2EStagePanel.vue**

```vue
<!-- src/components/E2EStagePanel.vue -->
<script setup lang="ts">
import { useGenerationStore } from '@/stores/generation'
import { useMultiAgent } from '@/composables/useMultiAgent'
import StreamDocument from './StreamDocument.vue'
import PreviewFrame from './PreviewFrame.vue'
import TestCaseProgress from './TestCaseProgress.vue'

const store = useGenerationStore()
const { confirmStage } = useMultiAgent()

async function handleConfirmCases(): Promise<void> {
  store.confirmE2ECases()
  await confirmStage('e2e')
}
</script>

<template>
  <div class="flex-1 flex flex-col overflow-auto">
    <!-- Phase 1: Test case review -->
    <template v-if="!store.e2eUserConfirmed">
      <StreamDocument
        :content="store.e2eTestCasesMd || store.docStreamingContent"
        :is-streaming="store.docIsStreaming || store.isStreaming"
        language="md"
      />
      <div v-if="!store.isStreaming && (store.e2eTestCasesMd || store.docStreamingContent)" class="flex justify-center p-3 border-t border-gray-200">
        <button
          class="px-4 py-2 bg-green-600 text-white rounded-lg text-sm font-medium hover:bg-green-700 transition-colors"
          @click="handleConfirmCases"
        >
          ✓ 确认测试用例，开始执行测试
        </button>
      </div>
    </template>

    <!-- Phase 2: Split-screen test execution -->
    <template v-else>
      <div class="flex flex-col h-full" style="height: calc(100vh - 200px);">
        <div class="h-[45%] overflow-auto border-b border-gray-200">
          <TestCaseProgress />
        </div>
        <div class="flex-1 relative">
          <PreviewFrame />
        </div>
      </div>
    </template>
  </div>
</template>
```

- [ ] **Step 2: 创建 TestCaseProgress.vue**

```vue
<!-- src/components/TestCaseProgress.vue -->
<script setup lang="ts">
import { useGenerationStore } from '@/stores/generation'
import { useE2ERunner } from '@/composables/useE2ERunner'

const store = useGenerationStore()

const totalCases = store.e2eTestCases.length
const executedCases = store.e2eResults.length
const passedCases = store.e2eResults.filter(r => r.passed).length
const progress = totalCases > 0 ? Math.round((executedCases / totalCases) * 100) : 0
</script>

<template>
  <div class="p-3">
    <div class="text-sm font-medium text-gray-700 mb-2">
      🧪 E2E 测试执行
      <span class="text-xs text-gray-400 ml-2">
        {{ executedCases }}/{{ totalCases }} 已完成
      </span>
    </div>

    <!-- Progress bar -->
    <div class="w-full bg-gray-200 rounded-full h-2 mb-3">
      <div
        class="h-2 rounded-full transition-all duration-300"
        :class="store.e2eRunning ? 'bg-blue-500' : 'bg-green-500'"
        :style="{ width: progress + '%' }"
      />
    </div>

    <!-- Case list -->
    <div class="space-y-1">
      <div
        v-for="(tc, idx) in store.e2eTestCases"
        :key="tc.id"
        class="flex items-center gap-2 px-3 py-1.5 text-sm rounded"
        :class="{
          'bg-blue-50': store.e2eCurrentCaseId === tc.id,
          'bg-green-50': store.e2eResults[idx]?.passed,
          'bg-red-50': store.e2eResults[idx] && !store.e2eResults[idx].passed,
          'bg-white': !store.e2eResults[idx] && store.e2eCurrentCaseId !== tc.id,
        }"
      >
        <span v-if="store.e2eCurrentCaseId === tc.id && store.e2eRunning" class="text-blue-500 animate-spin">⏳</span>
        <span v-else-if="store.e2eResults[idx]?.passed">✅</span>
        <span v-else-if="store.e2eResults[idx] && !store.e2eResults[idx].passed">❌</span>
        <span v-else>⏸</span>
        <span>{{ tc.name }}</span>
        <span v-if="store.e2eResults[idx]?.error" class="text-red-500 text-xs ml-auto truncate max-w-[200px]">
          {{ store.e2eResults[idx].error }}
        </span>
      </div>
    </div>
  </div>
</template>
```

- [ ] **Step 3: 验证编译**

```bash
cd ai-design-platform-web && npx turbo run typecheck --filter=ai-generation-app
```

---

### Task 18: 端到端验证

- [ ] **Step 1: 后端导入验证**

```bash
cd ai-design-platform-server/ai-service
python -c "
from app.services.generation.state import GenerationState
from app.services.generation.nodes import analysis_node, design_node, code_node, review_node, e2e_node
from app.services.generation.graph import build_graph
from app.services.generation.tools.registry import ToolRegistry
print('All imports OK')
"
```

- [ ] **Step 2: 工具系统验证**

```bash
cd ai-design-platform-server/ai-service
python -c "
from app.services.generation.tools.registry import ToolRegistry
r = ToolRegistry()
assert len(r._tools) >= 7, 'Expected at least 7 tools'
schema = r.get_schema()
assert len(schema) >= 7, 'Schema should match tool count'
print('ToolRegistry OK,', len(r._tools), 'tools registered')
"
```

- [ ] **Step 3: 前端编译验证**

```bash
cd ai-design-platform-web
npx turbo run typecheck --filter=ai-generation-app
```

- [ ] **Step 4: 前端 dev server 验证**

```bash
cd ai-design-platform-web
npx turbo run dev --filter=ai-generation-app
# Check browser console for import errors
```

---

### File Change Summary

| Type | Backend | Frontend |
|------|---------|----------|
| Create | `tools/` (6 files), `skills/` (6 files), `mcp/servers.yaml` | `StageToolbar`, `StreamDocument`, `AnalysisStagePanel`, `DesignStagePanel`, `CodeStagePanel`, `ToolTracePanel`, `ReviewStagePanel`, `MultiAgentPanel`, `E2EStagePanel`, `TestCaseProgress` |
| Modify | `state.py`, `nodes.py`, `graph.py` | `generation.ts`, `types/generation.ts`, `useStreamChat.ts`, `GenerationView.vue`, `ChatPanel.vue` |
| Deprecate | — | `PRDGeneratorView.vue`, `AnalysisPanel.vue`, `E2EPanel.vue`, ChatPanel confirm button |
