<!-- src/components/AgentLog.vue -->
<script setup lang="ts">
import { watch, ref, nextTick } from 'vue'
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
  if (status === 'running') return '\u{1F504}'
  if (status === 'done') return '✅'
  if (status === 'error') return '❌'
  return '\u{1F527}'
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
            <span>\u{1F4AD} 思考过程</span>
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
          <span>\u{1F4C4}</span>
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
          <div class="font-medium">\u{1F4CA} {{ entry.summary || '代码生成完成' }}</div>
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
