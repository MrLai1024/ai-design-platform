<!-- src/components/AgentLog.vue -->
<script setup lang="ts">
import { watch, ref, nextTick, computed } from 'vue'
import { useGenerationStore } from '@/stores/generation'
import type { AgentLogEntry } from '@/types/generation'

const props = defineProps<{
  entries: AgentLogEntry[]
  isStreaming: boolean
}>()

const emit = defineEmits<{
  'entry-click': [entry: AgentLogEntry]
  'send-feedback': [feedback: string]
  'cancel-generation': []
}>()

const store = useGenerationStore()
const scrollRef = ref<HTMLElement | null>(null)
const feedbackInput = ref<string>('')
const collapsedTasks = ref<Set<string>>(new Set())
const expandedFeedbacks = ref<Set<string>>(new Set())

const hasTaskGroups = computed(() => store.taskGroups.size > 0)

// Compute a scroll trigger key
const scrollKey = computed(() => {
  let key = `${props.entries.length}:`
  for (const [, group] of store.taskGroups) {
    key += `${group.taskId}:${group.entries.length}:${group.status}:`
    const last = group.entries.at(-1)
    if (last) key += `${last.id}:${last.type}:${last.toolStatus || ''}:`
  }
  const lastEntry = props.entries.at(-1)
  if (lastEntry) key += `:last:${lastEntry.id}:${lastEntry.type}`
  return key
})

function scrollToBottom(): void {
  nextTick(() => {
    if (scrollRef.value) {
      scrollRef.value.scrollTop = scrollRef.value.scrollHeight
      const thinkingBoxes = scrollRef.value.querySelectorAll('.thinking-box.streaming')
      thinkingBoxes.forEach((el) => {
        (el as HTMLElement).scrollTop = (el as HTMLElement).scrollHeight
      })
    }
  })
}

watch(scrollKey, scrollToBottom)
let scrollInterval: ReturnType<typeof setInterval> | null = null
watch(() => props.isStreaming, (streaming) => {
  if (streaming) {
    scrollInterval = setInterval(scrollToBottom, 300)
  } else {
    if (scrollInterval) { clearInterval(scrollInterval); scrollInterval = null }
  }
})

function toggleTask(taskId: string): void {
  if (collapsedTasks.value.has(taskId)) {
    collapsedTasks.value.delete(taskId)
  } else {
    collapsedTasks.value.add(taskId)
  }
  collapsedTasks.value = new Set(collapsedTasks.value)
}

function toggleFeedback(entryId: string): void {
  if (expandedFeedbacks.value.has(entryId)) {
    expandedFeedbacks.value.delete(entryId)
  } else {
    expandedFeedbacks.value.add(entryId)
  }
  expandedFeedbacks.value = new Set(expandedFeedbacks.value)
}

// ── Input handling ──
function handleKeydown(e: KeyboardEvent): void {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    sendFeedback()
  }
}

function sendFeedback(): void {
  const text = feedbackInput.value.trim()
  if (!text || props.isStreaming) return
  emit('send-feedback', text)
  feedbackInput.value = ''
}

function handleStop(): void {
  if (!props.isStreaming) return
  emit('cancel-generation')
}

// ── Rendering helpers ──
function toolIcon(status?: string): string {
  if (status === 'running') return '\u{1F504}'
  if (status === 'done') return '✅'
  if (status === 'error') return '❌'
  return '\u{1F527}'
}

function formatToolName(name?: string): string {
  const map: Record<string, string> = {
    create_file: '创建文件', write_code: '写入代码', compile_project: '编译检查',
    fix_error: '修复错误', use_skill: 'Skill 模板', mcp_query: 'MCP 查询',
    list_skills: '列出模板', get_compile_errors: '获取错误', delete_file: '删除文件',
    summarize_context: '压缩上下文', retrieve_context: '检索上下文', verify_contract: '契约校验',
  }
  return name ? (map[name] || name) : ''
}

function handleEntryClick(entry: AgentLogEntry): void {
  emit('entry-click', entry)
}

function taskStatusIcon(status: string): string {
  return status === 'done' ? '✅' : status === 'running' ? '\u{1F504}' : status === 'failed' ? '❌' : '⏳'
}

function taskTypeLabel(type: string): string {
  return type === 'bootstrap' ? '\u{1F527} 脚手架' : '\u{1F4BB} 业务'
}
</script>

<template>
  <div class="agent-log h-full flex flex-col bg-gray-50">
    <!-- scrollable log area -->
    <div ref="scrollRef" class="flex-1 overflow-y-auto p-2">
      <div class="text-xs font-medium text-gray-500 mb-2 px-1">AI 生成日志</div>

      <div class="space-y-1.5">
        <!-- Planner 推理文字 -->
        <div v-if="store.plannerReasoning" class="text-xs p-2 bg-purple-50 border border-purple-200 rounded text-purple-700 mb-2">
          <div class="font-medium mb-0.5">&#129504; Planner 分析</div>
          <div class="whitespace-pre-wrap text-[11px]">{{ store.plannerReasoning }}</div>
        </div>

        <!-- Task 分组视图 -->
        <template v-if="hasTaskGroups">
          <div
            v-for="task in store.plannerTasks"
            :key="task.id"
            class="border rounded overflow-hidden"
            :class="{
              'border-green-300': task.status === 'done',
              'border-blue-300': task.status === 'running',
              'border-red-300': task.status === 'failed',
              'border-gray-200': task.status === 'pending',
            }"
          >
            <div
              class="flex items-center gap-2 px-2 py-1.5 cursor-pointer hover:bg-gray-100 text-xs"
              :class="{
                'bg-green-50': task.status === 'done',
                'bg-blue-50': task.status === 'running',
                'bg-red-50': task.status === 'failed',
                'bg-gray-50': task.status === 'pending',
              }"
              @click="toggleTask(task.id)"
            >
              <span>{{ collapsedTasks.has(task.id) ? '▶' : '▼' }}</span>
              <span>{{ taskStatusIcon(task.status) }}</span>
              <span class="text-gray-400 text-[10px]">{{ taskTypeLabel(task.type) }}</span>
              <span class="font-medium truncate flex-1">{{ task.description }}</span>
              <span class="text-gray-400 text-[10px]">{{ task.files.length }} files</span>
            </div>
            <div v-if="!collapsedTasks.has(task.id)" class="border-t border-gray-100">
              <template v-for="entry in store.taskGroups.get(task.id)?.entries || []" :key="entry.id">
                <div v-if="entry.type === 'thinking'" class="text-xs px-2 py-0.5">
                  <div class="flex items-center gap-1 text-gray-400 mb-0.5">
                    <span>&#128173;</span>
                    <span v-if="!entry.thinkingDone" class="text-blue-400 animate-pulse">...</span>
                  </div>
                  <div class="thinking-box p-1.5 bg-white rounded border border-gray-100 text-gray-600 whitespace-pre-wrap max-h-[120px] overflow-y-auto text-[10px] leading-relaxed"
                       :class="{ streaming: !entry.thinkingDone }">{{ entry.thinkingText?.slice(-300) }}</div>
                </div>
                <div v-else-if="entry.type === 'tool_call'"
                     class="flex items-center gap-1.5 px-2 py-0.5 text-[10px] cursor-pointer hover:bg-gray-50 border-b border-gray-50"
                     :class="{ 'text-blue-600': entry.toolStatus === 'running', 'text-green-600': entry.toolStatus === 'done', 'text-red-600': entry.toolStatus === 'error' }"
                     @click="handleEntryClick(entry)">
                  <span>{{ toolIcon(entry.toolStatus) }}</span>
                  <span class="font-mono">{{ formatToolName(entry.toolName) }}</span>
                  <span v-if="entry.toolArgs?.path" class="text-gray-400 truncate">→ {{ entry.toolArgs.path }}</span>
                </div>
                <div v-else-if="entry.type === 'file_start'"
                     class="flex items-center gap-1.5 px-2 py-0.5 text-[10px] cursor-pointer hover:bg-gray-50"
                     :class="{ 'text-blue-600': !entry.fileDone, 'text-green-600': entry.fileDone }"
                     @click="handleEntryClick(entry)">
                  <span>&#128196;</span>
                  <span class="font-mono">{{ entry.filePath }}</span>
                  <span v-if="entry.fileDone" class="text-green-500 ml-auto">✅</span>
                  <span v-else class="text-blue-400 animate-pulse ml-auto text-[9px]">生成中...</span>
                </div>
                <div v-else-if="entry.type === 'compile'"
                     class="px-2 py-0.5 text-[10px] border-b border-gray-50"
                     :class="entry.compileOk ? 'text-green-600' : 'text-red-600'">
                  ⚡ 编译{{ entry.compileOk ? '✅' : '❌ ' + (entry.compileErrors?.length || 0) + ' errors' }}
                </div>
              </template>
              <div v-if="(store.taskGroups.get(task.id)?.entries.length || 0) === 0 && task.status === 'pending'"
                   class="text-center text-gray-400 text-[10px] py-2">等待执行...</div>
            </div>
          </div>
        </template>

        <!-- Fallback: 无 task 分组 -->
        <template v-if="!hasTaskGroups">
          <template v-for="entry in entries" :key="entry.id">
            <!-- Cancel card -->
            <div v-if="entry.type === 'cancel'"
                 class="p-2 rounded border text-xs bg-orange-50 border-orange-200 text-orange-700">
              <div class="flex items-center gap-1 font-medium">⏹ 用户终止执行</div>
              <div v-if="entry.summary" class="text-[10px] text-orange-500 mt-0.5">{{ entry.summary }}</div>
            </div>

            <!-- Feedback summary card -->
            <div v-else-if="entry.type === 'feedback_summary'"
                 class="border rounded overflow-hidden border-gray-300">
              <div class="flex items-center gap-2 px-2 py-1.5 cursor-pointer hover:bg-gray-100 text-xs bg-yellow-50"
                   @click="toggleFeedback(entry.id)">
                <span>{{ expandedFeedbacks.has(entry.id) ? '▼' : '▶' }}</span>
                <span>💬</span>
                <span class="font-medium truncate flex-1">用户反馈：{{ entry.feedbackText?.slice(0, 40) }}{{ (entry.feedbackText?.length || 0) > 40 ? '...' : '' }}</span>
                <span class="text-gray-400 text-[10px]">{{ entry.feedbackResult || '处理中...' }}</span>
              </div>
              <div v-if="expandedFeedbacks.has(entry.id) && entry.feedbackText"
                   class="border-t border-gray-100 p-2 bg-white">
                <div class="text-[10px] text-gray-600 whitespace-pre-wrap mb-1">"{{ entry.feedbackText }}"</div>
                <div class="text-[10px] text-gray-400">{{ entry.feedbackResult }}</div>
              </div>
            </div>

            <!-- Existing entry types (thinking, tool_call, file_start, compile, phase_summary) -->
            <div v-if="entry.type === 'thinking'" class="text-xs">
              <div class="flex items-center gap-1 text-gray-400 mb-0.5 px-1">
                <span>&#128173; 思考过程</span>
                <span v-if="!entry.thinkingDone" class="text-blue-400 animate-pulse">...</span>
              </div>
              <div class="thinking-box p-2 bg-white rounded border border-gray-200 text-gray-600 whitespace-pre-wrap max-h-[150px] overflow-y-auto text-[11px] leading-relaxed"
                   :class="{ streaming: !entry.thinkingDone }">{{ entry.thinkingText }}</div>
            </div>
            <div v-else-if="entry.type === 'tool_call'"
                 class="flex items-center gap-2 px-2 py-1 bg-white rounded border border-gray-200 text-xs cursor-pointer hover:bg-gray-50"
                 :class="{ 'border-blue-300 bg-blue-50': entry.toolStatus === 'running', 'border-red-300 bg-red-50': entry.toolStatus === 'error' }"
                 @click="handleEntryClick(entry)">
              <span>{{ toolIcon(entry.toolStatus) }}</span>
              <span class="font-mono text-blue-600">{{ formatToolName(entry.toolName) }}</span>
              <span v-if="entry.toolArgs?.path" class="text-gray-500 truncate">→ {{ entry.toolArgs.path }}</span>
              <span v-if="entry.toolArgs?.name" class="text-purple-500 truncate">→ {{ entry.toolArgs.name }}</span>
              <span v-if="entry.toolDetail" class="text-gray-400 ml-auto text-[10px] truncate max-w-[120px]">{{ entry.toolDetail }}</span>
            </div>
            <div v-else-if="entry.type === 'file_start'"
                 class="flex items-center gap-2 px-2 py-1 text-xs cursor-pointer hover:bg-gray-100 rounded"
                 :class="{ 'text-blue-600': !entry.fileDone, 'text-green-600': entry.fileDone }"
                 @click="handleEntryClick(entry)">
              <span>&#128196;</span>
              <span class="font-mono">{{ entry.filePath }}</span>
              <span v-if="!entry.fileDone" class="text-blue-400 animate-pulse text-[10px]">生成中...</span>
              <span v-else class="text-green-500 text-[10px]">✅</span>
            </div>
            <div v-else-if="entry.type === 'compile'"
                 class="p-2 rounded border text-xs"
                 :class="entry.compileOk ? 'bg-green-50 border-green-200 text-green-700' : 'bg-red-50 border-red-200 text-red-700'">
              <div class="flex items-center gap-1 font-medium mb-0.5">
                <span>⚡ 编译{{ entry.compileOk ? '通过' : '失败' }}</span>
                <span v-if="entry.compileOk">✅</span>
                <span v-else>❌ {{ entry.compileErrors?.length || 0 }} errors</span>
              </div>
              <div v-if="!entry.compileOk && entry.compileErrors" class="space-y-0.5 mt-1">
                <div v-for="(err, i) in entry.compileErrors.slice(0, 5)" :key="i"
                     class="text-[10px] text-red-600 cursor-pointer hover:underline"
                     @click="handleEntryClick(entry)">{{ err.file }}:{{ err.line }} — {{ err.message }}</div>
              </div>
            </div>
            <div v-else-if="entry.type === 'phase_summary'"
                 class="p-2 rounded border text-xs bg-blue-50 border-blue-200 text-blue-700">
              <div class="font-medium">&#128202; {{ entry.summary || '代码生成完成' }}</div>
              <div v-if="entry.fileTotal" class="text-[10px] text-blue-500 mt-0.5">{{ entry.fileTotal }} 个文件</div>
            </div>
          </template>
        </template>

        <div v-if="entries.length === 0 && isStreaming" class="text-center text-gray-400 text-xs py-4">
          等待 AI 开始生成...
        </div>
      </div>
    </div>

    <!-- fixed footer: input + stop -->
    <div class="flex items-center gap-2 px-2 py-1.5 border-t border-gray-200 bg-white">
      <textarea
        v-model="feedbackInput"
        :placeholder="isStreaming ? '生成中...' : '📝 输入修改意见，Enter 发送'"
        :disabled="isStreaming"
        rows="1"
        class="flex-1 text-xs px-2 py-1.5 border border-gray-300 rounded resize-none bg-gray-50 focus:outline-none focus:border-blue-400 disabled:bg-gray-100 disabled:text-gray-400"
        @keydown="handleKeydown"
      />
      <button
        :class="isStreaming ? 'bg-red-500 hover:bg-red-600 cursor-pointer' : 'bg-gray-300 cursor-not-allowed'"
        class="text-white text-xs px-3 py-1.5 rounded transition-colors shrink-0"
        :disabled="!isStreaming"
        @click="handleStop"
      >⏹ 停止</button>
    </div>
  </div>
</template>

<style scoped>
.agent-log {
  scroll-behavior: smooth;
}
.feedback-input:disabled {
  cursor: not-allowed;
}
</style>
