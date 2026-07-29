# 功能开发节点 AgentLog + 三栏布局 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 功能开发节点三栏重构：左侧 AgentLog 流式 AI 输出（思考+工具+编译），中间 FileTree，右侧 CodeView。后端 code_node 改为 streaming 模式实时发射事件。

**Architecture:** 新增 `AgentLog.vue` 渲染流式事件流，`useCodeStream.ts` composable 消费 SSE 事件。后端 `code_node_streaming` 通过 `asyncio.Queue` 在工具循环中实时发射事件，`graph.py` Phase 3 并行读队列 + 等待 task。

**Tech Stack:** Vue 3 (Composition API + Pinia + Tailwind), TypeScript, Python (LangGraph + asyncio + structlog)

---

## File Structure

```
前端新增:
  src/components/AgentLog.vue          — AI 流式输出区（思考/工具/文件/编译）
  src/composables/useCodeStream.ts     — 代码阶段 SSE 事件消费

前端修改:
  src/types/generation.ts              — 新增 AgentLogEntry 类型
  src/stores/generation.ts             — 新增 agentLogEntries state + actions
  src/components/CodeStagePanel.vue    — 工程文件 tab 改为三栏
  src/composables/useMultiAgent.ts     — dispatchGraphEvent 路由代码事件

后端修改:
  ai-service/app/services/generation/nodes.py   — 新增 code_node_streaming
  ai-service/app/services/generation/graph.py   — Phase 3 改为队列驱动
```

---

### Task 1: Add AgentLogEntry type

**Files:**
- Modify: `ai-design-platform-web/packages/ai-generation-app/src/types/generation.ts`

- [ ] **Step 1: Add AgentLogEntry interface**

Append to `src/types/generation.ts`:

```typescript
// ── AgentLog Types ──

export interface CompileErrorEntry {
  file: string
  line: number
  message: string
}

export interface AgentLogEntry {
  id: string
  type: 'thinking' | 'tool_call' | 'tool_result' | 'file_start'
       | 'file_complete' | 'compile' | 'phase_summary'
  timestamp: number
  thinkingText?: string
  thinkingDone?: boolean
  toolName?: string
  toolArgs?: Record<string, any>
  toolStatus?: 'running' | 'done' | 'error'
  toolDetail?: string
  filePath?: string
  fileTotal?: number
  fileDone?: boolean
  compileOk?: boolean
  compileErrors?: CompileErrorEntry[]
  summary?: string
}
```

---

### Task 2: Extend generation store

**Files:**
- Modify: `ai-design-platform-web/packages/ai-generation-app/src/stores/generation.ts`

- [ ] **Step 1: Add import**

After existing imports:
```typescript
import type { AgentLogEntry } from '@/types/generation'
```

- [ ] **Step 2: Add state field**

After `toolTraces`:
```typescript
const agentLogEntries = ref<AgentLogEntry[]>([])
```

- [ ] **Step 3: Add actions**

After `setCodeGenDone`:
```typescript
function addAgentLogEntry(entry: AgentLogEntry): void {
  agentLogEntries.value.push(entry)
}

function updateLastAgentLogEntry(patch: Partial<AgentLogEntry>): void {
  const last = agentLogEntries.value.at(-1)
  if (last) Object.assign(last, patch)
}
```

- [ ] **Step 4: Update resetAll**

In resetAll, add:
```typescript
agentLogEntries.value = []
```

- [ ] **Step 5: Update return block**

Add to return:
```typescript
agentLogEntries, addAgentLogEntry, updateLastAgentLogEntry,
```

---

### Task 3: Create AgentLog.vue

**Files:**
- Create: `ai-design-platform-web/packages/ai-generation-app/src/components/AgentLog.vue`

- [ ] **Step 1: Create the component**

```vue
<!-- src/components/AgentLog.vue -->
<script setup lang="ts">
import { watch, ref, nextTick } from 'vue'
import { useGenerationStore } from '@/stores/generation'
import type { AgentLogEntry } from '@/types/generation'

const props = defineProps<{
  entries: AgentLogEntry[]
  isStreaming: boolean
}>()

const emit = defineEmits<{
  'entry-click': [entry: AgentLogEntry]
}>()

const containerRef = ref<HTMLElement | null>(null)

function scrollToBottom(): void {
  nextTick(() => {
    if (containerRef.value) {
      containerRef.value.scrollTop = containerRef.value.scrollHeight
    }
  })
}

watch(() => props.entries.length, scrollToBottom)

function toolIcon(status?: string): string {
  if (status === 'running') return '🔄'
  if (status === 'done') return '✅'
  if (status === 'error') return '❌'
  return '🔧'
}

function formatToolName(name?: string): string {
  const map: Record<string, string> = {
    create_file: '创建文件',
    write_code: '写入代码',
    compile_project: '编译检查',
    fix_error: '修复错误',
    use_skill: 'Skill 模板',
    mcp_query: 'MCP 查询',
    list_skills: '列出模板',
    get_compile_errors: '获取错误',
    delete_file: '删除文件',
  }
  return name ? (map[name] || name) : ''
}

function handleEntryClick(entry: AgentLogEntry): void {
  emit('entry-click', entry)
}
</script>

<template>
  <div ref="containerRef" class="agent-log h-full overflow-y-auto bg-gray-50 p-2">
    <div class="text-xs font-medium text-gray-500 mb-2 px-1">AI 生成日志</div>

    <div class="space-y-1.5">
      <template v-for="entry in entries" :key="entry.id">
        <!-- 思考气泡 -->
        <div v-if="entry.type === 'thinking'" class="text-xs">
          <div class="flex items-center gap-1 text-gray-400 mb-0.5 px-1">
            <span>💭 思考过程</span>
            <span v-if="!entry.thinkingDone" class="text-blue-400 animate-pulse">...</span>
          </div>
          <div class="p-2 bg-white rounded border border-gray-200 text-gray-600 whitespace-pre-wrap max-h-[150px] overflow-y-auto text-[11px] leading-relaxed">
            {{ entry.thinkingText }}
          </div>
        </div>

        <!-- 工具卡片 -->
        <div
          v-else-if="entry.type === 'tool_call'"
          class="flex items-center gap-2 px-2 py-1 bg-white rounded border border-gray-200 text-xs cursor-pointer hover:bg-gray-50"
          :class="{
            'border-blue-300 bg-blue-50': entry.toolStatus === 'running',
            'border-red-300 bg-red-50': entry.toolStatus === 'error',
          }"
          @click="handleEntryClick(entry)"
        >
          <span>{{ toolIcon(entry.toolStatus) }}</span>
          <span class="font-mono text-blue-600">{{ formatToolName(entry.toolName) }}</span>
          <span v-if="entry.toolArgs?.path" class="text-gray-500 truncate">→ {{ entry.toolArgs.path }}</span>
          <span v-if="entry.toolArgs?.name" class="text-purple-500 truncate">→ {{ entry.toolArgs.name }}</span>
          <span v-if="entry.toolDetail" class="text-gray-400 ml-auto text-[10px] truncate max-w-[120px]">{{ entry.toolDetail }}</span>
        </div>

        <!-- 文件开始 -->
        <div
          v-else-if="entry.type === 'file_start'"
          class="flex items-center gap-2 px-2 py-1 text-xs cursor-pointer hover:bg-gray-100 rounded"
          :class="{ 'text-blue-600': !entry.fileDone, 'text-green-600': entry.fileDone }"
          @click="handleEntryClick(entry)"
        >
          <span>📄</span>
          <span class="font-mono">{{ entry.filePath }}</span>
          <span v-if="!entry.fileDone" class="text-blue-400 animate-pulse text-[10px]">生成中...</span>
          <span v-else class="text-green-500 text-[10px]">✅</span>
        </div>

        <!-- 编译状态 -->
        <div
          v-else-if="entry.type === 'compile'"
          class="p-2 rounded border text-xs"
          :class="entry.compileOk
            ? 'bg-green-50 border-green-200 text-green-700'
            : 'bg-red-50 border-red-200 text-red-700'"
        >
          <div class="flex items-center gap-1 font-medium mb-0.5">
            <span>⚡ 编译{{ entry.compileOk ? '通过' : '失败' }}</span>
            <span v-if="entry.compileOk">✅</span>
            <span v-else>❌ {{ entry.compileErrors?.length || 0 }} errors</span>
          </div>
          <div v-if="!entry.compileOk && entry.compileErrors" class="space-y-0.5 mt-1">
            <div
              v-for="(err, i) in entry.compileErrors.slice(0, 5)"
              :key="i"
              class="text-[10px] text-red-600 cursor-pointer hover:underline"
              @click="handleEntryClick(entry)"
            >
              {{ err.file }}:{{ err.line }} — {{ err.message }}
            </div>
          </div>
        </div>

        <!-- 阶段汇总 -->
        <div
          v-else-if="entry.type === 'phase_summary'"
          class="p-2 rounded border text-xs bg-blue-50 border-blue-200 text-blue-700"
        >
          <div class="font-medium">📊 {{ entry.summary || '代码生成完成' }}</div>
          <div v-if="entry.fileTotal" class="text-[10px] text-blue-500 mt-0.5">
            {{ entry.fileTotal }} 个文件
          </div>
        </div>
      </template>

      <div v-if="entries.length === 0 && isStreaming" class="text-center text-gray-400 text-xs py-4">
        等待 AI 开始生成...
      </div>
    </div>
  </div>
</template>

<style scoped>
.agent-log {
  scroll-behavior: smooth;
}
</style>
```

---

### Task 4: Create useCodeStream composable

**Files:**
- Create: `ai-design-platform-web/packages/ai-generation-app/src/composables/useCodeStream.ts`

- [ ] **Step 1: Create the composable**

```typescript
// src/composables/useCodeStream.ts
import { useGenerationStore } from '@/stores/generation'
import type { AgentLogEntry } from '@/types/generation'

let _store: ReturnType<typeof useGenerationStore> | null = null

function store() {
  if (!_store) _store = useGenerationStore()
  return _store
}

function entryId(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 7)
}

export function handleCodeSSEEvent(event: any): void {
  const s = store()
  const t = event._t

  switch (t) {
    case 'code_gen_start': {
      s.agentLogEntries.push({
        id: entryId(), type: 'phase_summary', timestamp: Date.now(),
        fileTotal: event.files?.length,
        summary: `开始生成 ${event.files?.length || 0} 个文件`,
      })
      s.initFileTree(event.files || [])
      break
    }

    case 'thinking_chunk': {
      const last = s.agentLogEntries.at(-1)
      if (last?.type === 'thinking' && !last.thinkingDone) {
        last.thinkingText = (last.thinkingText || '') + (event.text || '')
      } else {
        s.agentLogEntries.push({
          id: entryId(), type: 'thinking', timestamp: Date.now(),
          thinkingText: event.text || '',
        })
      }
      break
    }

    case 'tool_call': {
      s.agentLogEntries.push({
        id: entryId(), type: 'tool_call', timestamp: Date.now(),
        toolName: event.tool, toolArgs: event.args, toolStatus: 'running',
      })
      break
    }

    case 'tool_result': {
      const running = findLastRunningToolCall(s.agentLogEntries, event.tool)
      if (running) {
        running.toolStatus = event.ok ? 'done' : 'error'
        running.toolDetail = event.detail?.path
          ? `→ ${event.detail.path}`
          : (event.ok ? 'Done' : 'Failed')
      }
      break
    }

    case 'file_start': {
      s.agentLogEntries.push({
        id: entryId(), type: 'file_start', timestamp: Date.now(),
        filePath: event.path,
      })
      s.setCurrentGeneratingFile(event.path)
      break
    }

    case 'file_chunk': {
      s.appendFileContent(event.path, event.content || '')
      break
    }

    case 'file_complete': {
      const fileEntry = s.agentLogEntries.findLast(
        e => e.type === 'file_start' && e.filePath === event.path
      )
      if (fileEntry) fileEntry.fileDone = true
      s.finalizeFile(event.path)
      break
    }

    case 'compile_status': {
      s.agentLogEntries.push({
        id: entryId(), type: 'compile', timestamp: Date.now(),
        compileOk: event.ok,
        compileErrors: event.errors || [],
      })
      break
    }

    case 'code_gen_done': {
      s.agentLogEntries.push({
        id: entryId(), type: 'phase_summary', timestamp: Date.now(),
        summary: `生成完成：${event.total_files || 0} 个文件，${event.compile_errors || 0} 个错误`,
        fileTotal: event.total_files,
      })
      break
    }
  }
}

function findLastRunningToolCall(entries: AgentLogEntry[], tool: string): AgentLogEntry | undefined {
  for (let i = entries.length - 1; i >= 0; i--) {
    const e = entries[i]!
    if (e.type === 'tool_call' && e.toolName === tool && e.toolStatus === 'running') {
      return e
    }
  }
  return undefined
}
```

---

### Task 5: Route code events in dispatchGraphEvent

**Files:**
- Modify: `ai-design-platform-web/packages/ai-generation-app/src/composables/useMultiAgent.ts`

- [ ] **Step 1: Add import**

```typescript
import { handleCodeSSEEvent } from './useCodeStream'
```

- [ ] **Step 2: Add cases in dispatchGraphEvent**

In the `dispatchGraphEvent` switch, add cases for code events:

```typescript
case 'code_gen_start':
case 'thinking_chunk':
case 'tool_call':
case 'tool_result':
case 'file_start':
case 'file_complete':
case 'compile_status':
case 'code_gen_done':
  handleCodeSSEEvent(event)
  break
```

Note: `file_chunk` already handled by existing `'file_chunk'` case which calls `store.appendFileContent` + `store.finalizeFile`. Keep the existing handler and add the code-specific logic inside the new cases.

---

### Task 6: Update CodeStagePanel to three-column layout

**Files:**
- Modify: `ai-design-platform-web/packages/ai-generation-app/src/components/CodeStagePanel.vue`

- [ ] **Step 1: Rewrite the component**

```vue
<!-- src/components/CodeStagePanel.vue -->
<script setup lang="ts">
import { computed } from 'vue'
import { useGenerationStore } from '@/stores/generation'
import TabBar from './TabBar.vue'
import PreviewFrame from './PreviewFrame.vue'
import FileExplorer from './FileExplorer.vue'
import AgentLog from './AgentLog.vue'
import type { AgentLogEntry } from '@/types/generation'

const store = useGenerationStore()

const currentTab = computed(() => store.codeViewTab === 'preview' ? 'preview' : 'files')

const codeTabs = [
  { key: 'files' as const, label: '工程文件' },
  { key: 'preview' as const, label: '实时预览' },
  { key: 'trace' as const, label: 'Tool Trace' },
]

function handleTabSelect(key: string): void {
  if (key === 'preview' || key === 'files' || key === 'trace') {
    store.setCodeViewTab(key)
  }
}

function onAgentLogClick(entry: AgentLogEntry): void {
  // If entry has a file path, open it
  const path = entry.filePath || entry.toolArgs?.path
  if (path && store.files.has(path)) {
    store.setActiveFile(path)
    store.setCodeViewTab('files')
  }
}
</script>

<template>
  <div class="flex-1 flex flex-col">
    <TabBar
      :tabs="codeTabs"
      :active-tab="currentTab"
      @select="handleTabSelect"
    />
    <div class="flex-1 relative">
      <!-- 预览 tab -->
      <div v-show="currentTab === 'preview'" class="absolute inset-0">
        <PreviewFrame />
      </div>

      <!-- Tool Trace tab (keep existing) -->
      <div v-show="currentTab === 'trace'" class="absolute inset-0">
        <slot name="trace">
          <div class="flex items-center justify-center h-full text-gray-400 text-sm">
            Tool Trace
          </div>
        </slot>
      </div>

      <!-- 工程文件 tab: 三栏布局 -->
      <div v-show="currentTab === 'files'" class="absolute inset-0 flex overflow-hidden">
        <!-- 左: AgentLog 35% -->
        <div class="w-[35%] min-w-[280px] border-r border-gray-200 flex flex-col">
          <AgentLog
            :entries="store.agentLogEntries"
            :is-streaming="store.isStreaming"
            @entry-click="onAgentLogClick"
          />
        </div>

        <!-- 中/右: FileExplorer (FileTree + CodeView) 65% -->
        <div class="flex-1">
          <FileExplorer />
        </div>
      </div>
    </div>
  </div>
</template>
```

---

### Task 7: Backend — code_node_streaming

**Files:**
- Modify: `ai-design-platform-server/ai-service/app/services/generation/nodes.py`

- [ ] **Step 1: Add make_event helper**

At top of nodes.py, after imports:

```python
import asyncio as _asyncio

def _make_queue_event(event_type: str, stage: str, data: dict) -> dict:
    return {"event_type": event_type, "stage": stage, "data": data}
```

- [ ] **Step 2: Add code_node_streaming function**

After the existing `code_node`, add:

```python
async def code_node_streaming(
    state: GenerationState,
    queue: _asyncio.Queue,
) -> GenerationState:
    """代码生成节点 — streaming 版本，每步工具调用通过 queue 实时发射事件."""

    import tempfile, os as _os, json as _json

    project_root = _os.path.join(
        tempfile.gettempdir(),
        "ai-gen",
        state.get("requirement", "project")[:20].replace(" ", "_"),
    )

    from .tools.registry import ToolRegistry
    registry = ToolRegistry(project_root)
    tools_schema = registry.get_schema()

    design_doc = state.get("design_doc") or state.get("design_result", "")
    failure = state.get("failure_details")
    system_prompt = CODE_ORCHESTRATOR_PROMPT

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

    # Plan files first
    planned_files = _estimate_files(design_doc)
    queue.put_nowait(_make_queue_event("code_gen_start", "code", {
        "files": planned_files,
    }))

    for round_idx in range(max_tool_rounds):
        logger.info("code_tool_round", round=round_idx + 1)

        thinking_text_parts = []

        def on_thinking(text: str):
            thinking_text_parts.append(text)
            queue.put_nowait(_make_queue_event("thinking_chunk", "code", {"text": text}))

        try:
            response = await _llm_generate_with_tools_streaming(
                messages=messages,
                tools=tools_schema,
                model="glm-5.2",
                on_thinking=on_thinking,
            )
        except Exception as e:
            logger.error("llm_tool_call_error", error=str(e))
            break

        if response.get("tool_calls"):
            for tc in response["tool_calls"]:
                tool_name = tc["function"]["name"]
                try:
                    tool_args = _json.loads(tc["function"]["arguments"])
                except _json.JSONDecodeError:
                    tool_args = {}

                queue.put_nowait(_make_queue_event("tool_call", "code", {
                    "tool": tool_name,
                    "args": tool_args,
                    "status": "running",
                }))

                result = await registry.invoke(tool_name, tool_args)

                queue.put_nowait(_make_queue_event("tool_result", "code", {
                    "tool": tool_name,
                    "ok": result.ok,
                    "detail": result.data,
                }))

                if tool_name in ("create_file", "write_code") and result.ok:
                    path = tool_args.get("path", "")
                    content = tool_args.get("content", "")
                    if tool_name == "write_code" and content:
                        generated_files[path] = content
                        queue.put_nowait(_make_queue_event("file_start", "code", {"path": path}))
                        chunk_size = 200
                        for i in range(0, len(content), chunk_size):
                            queue.put_nowait(_make_queue_event("file_chunk", "code", {
                                "path": path,
                                "content": content[i:i + chunk_size],
                            }))
                        queue.put_nowait(_make_queue_event("file_complete", "code", {"path": path}))

                elif tool_name == "use_skill" and result.ok:
                    for f in result.data.get("files", []):
                        generated_files[f["path"]] = f["content"]
                        content = f["content"]
                        queue.put_nowait(_make_queue_event("file_start", "code", {"path": f["path"]}))
                        chunk_size = 200
                        for i in range(0, len(content), chunk_size):
                            queue.put_nowait(_make_queue_event("file_chunk", "code", {
                                "path": f["path"],
                                "content": content[i:i + chunk_size],
                            }))
                        queue.put_nowait(_make_queue_event("file_complete", "code", {"path": f["path"]}))
                        # Write to disk
                        _os.makedirs(_os.path.dirname(_os.path.join(project_root, f["path"])), exist_ok=True)
                        with open(_os.path.join(project_root, f["path"]), "w", encoding="utf-8") as wf:
                            wf.write(content)

                elif tool_name == "compile_project":
                    errors = result.data.get("errors", []) if not result.ok else []
                    last_compile_errors = errors if not result.ok else None
                    queue.put_nowait(_make_queue_event("compile_status", "code", {
                        "ok": result.ok,
                        "errors": errors,
                    }))

                messages.append({"role": "assistant", "content": None, "tool_calls": [tc]})
                messages.append({"role": "tool", "tool_call_id": tc["id"],
                    "content": _json.dumps({"ok": result.ok, "data": result.data, "error": result.error},
                    ensure_ascii=False)})

        elif response.get("content"):
            messages.append({"role": "assistant", "content": response["content"]})
            if "__CODE_GEN_DONE__" in (response.get("content") or ""):
                logger.info("code_gen_done_signal")
                break

        # Auto-compile every 3 rounds
        if round_idx > 0 and round_idx % 3 == 0 and generated_files:
            compile_result = await registry.invoke("compile_project", {})
            ok = compile_result.ok
            errors = compile_result.data.get("errors", []) if not ok else []
            queue.put_nowait(_make_queue_event("compile_status", "code", {
                "ok": ok, "errors": errors,
            }))
            if ok and not errors:
                break

    queue.put_nowait(_make_queue_event("code_gen_done", "code", {
        "total_files": len(generated_files),
        "compile_errors": len(last_compile_errors) if last_compile_errors else 0,
    }))

    state["generated_files"] = generated_files
    state["compile_errors"] = last_compile_errors
    state["code_result"] = _json.dumps(generated_files, ensure_ascii=False)
    state["stage_phase"] = "complete"
    return state


def _estimate_files(design_doc: str) -> list[str]:
    """Estimate the file list from design doc (for code_gen_start event)."""
    files = []
    for line in design_doc.split("\n"):
        line = line.strip()
        if line.endswith(".vue") or line.endswith(".ts") or line.endswith(".js"):
            files.append(line)
    if not files:
        files = ["App.vue", "components/Header.vue"]
    return files
```

- [ ] **Step 3: Add _llm_generate_with_tools_streaming**

After `_llm_generate_with_tools`, add the streaming variant:

```python
async def _llm_generate_with_tools_streaming(
    messages: list[dict],
    tools: list[dict],
    model: str = "glm-5.2",
    on_thinking: Any | None = None,
) -> dict:
    """Call LLM with tools — streaming thinking via callback."""
    tool_prompt = (
        "\n\n你可以调用以下工具函数。要调用工具，在回复中输出 JSON：\n"
        '{"tool_calls": [{"id": "call_1", "function": {"name": "工具名", "arguments": "{\\"key\\": \\"value\\"}"}}]}\n'
        "可用工具：\n" + json.dumps(tools, ensure_ascii=False, indent=2) + "\n"
        "如果不需要调用工具，直接输出文本回复。"
    )

    messages_with_tools = list(messages)
    if messages_with_tools and messages_with_tools[0]["role"] == "system":
        messages_with_tools[0] = {
            "role": "system",
            "content": messages_with_tools[0]["content"] + tool_prompt,
        }
    else:
        messages_with_tools.insert(0, {"role": "system", "content": tool_prompt})

    prompt_text = ""
    for m in messages_with_tools:
        role = m.get("role", "?")
        content = m.get("content", "")
        if content is None and m.get("tool_calls"):
            content = json.dumps(m["tool_calls"], ensure_ascii=False)
        prompt_text += f"\n[{role}]: {content or ''}"

    raw = await _llm_generate(
        system_prompt=prompt_text[:500],
        user_content=prompt_text[500:],
        model=model,
        enable_thinking=True,
        on_reasoning=on_thinking,
    )

    try:
        parsed = json.loads(raw.strip())
        if "tool_calls" in parsed:
            return {"content": None, "tool_calls": parsed["tool_calls"]}
    except (json.JSONDecodeError, KeyError):
        pass

    return {"content": raw.strip(), "tool_calls": None}
```

---

### Task 8: Update graph.py Phase 3

**Files:**
- Modify: `ai-design-platform-server/ai-service/app/services/generation/graph.py`

- [ ] **Step 1: Replace Phase 3 with streaming version**

Replace the Phase 3 section (from `# ── Phase 3: Code generation ──` to the `return` before Phase 4) with:

```python
        # ── Phase 3: Code generation (streaming via event queue) ──
        if not state.get("generated_files"):
            import asyncio as _asyncio
            from .nodes import code_node_streaming

            yield self._make_event("stage_start", "code", {"phase": "generating"})

            event_queue: _asyncio.Queue = _asyncio.Queue()

            gen_task = _asyncio.create_task(
                code_node_streaming(state, event_queue)
            )

            # Forward events from queue while code_node runs
            while not gen_task.done() or not event_queue.empty():
                try:
                    evt = await _asyncio.wait_for(event_queue.get(), timeout=0.1)
                    yield evt
                except _asyncio.TimeoutError:
                    pass

            updated_state = gen_task.result()
            generated_files = updated_state.get("generated_files", {})
            compile_errors = updated_state.get("compile_errors")

            state["code_result"] = updated_state.get("code_result", "")
            state["generated_files"] = generated_files
            state["compile_errors"] = compile_errors
            state["stage_phase"] = "complete"

            yield self._make_event("stage_complete", "code", {
                "summary": f"Generated {len(generated_files)} files",
            })
            yield self._make_event("human_confirm_required", "code", {
                "message": "Please review the code output.",
            })
            return
```

---

### Task 9: Verification

- [ ] **Step 1: Verify backend imports**

```bash
cd ai-design-platform-server/ai-service
python -c "from app.services.generation.nodes import code_node_streaming, _llm_generate_with_tools_streaming; print('OK')"
```

- [ ] **Step 2: Verify frontend compilation**

```bash
cd ai-design-platform-web
npx vue-tsc --noEmit --project packages/ai-generation-app/tsconfig.json 2>&1 | grep -E "^src" | grep -v "PRDGeneratorView" | grep -v "public-path" | grep -v "main.ts" | head -20
```

Expected: no new type errors.

- [ ] **Step 3: End-to-end test**

```bash
# Start AI service + gateway, then test code generation via API
curl -s -N -X POST "http://localhost:8080/api/v1/generation/stream" \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"# PRD\n## design\ncomponent: Header"}],"model":"glm-5.2","mode":"graph","skip_analysis":true,"component_lib":"tailwind"}' \
  2>&1 | timeout 30 head -20
```

Expected: events including `code_gen_start`, `thinking_chunk`, `tool_call`, `file_chunk`, `compile_status`.
