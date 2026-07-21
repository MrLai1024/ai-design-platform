<!-- src/components/AnalysisStagePanel.vue -->
<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'
import { useGenerationStore } from '@/stores/generation'
import StreamDocument from './StreamDocument.vue'

const store = useGenerationStore()
const reasoningRef = ref<HTMLElement | null>(null)
const reasoningManuallyOpen = ref(true) // user toggle

function isReasoningOpen(): boolean {
  // Still thinking: auto-expand
  if (store.prdReasoningContent && store.prdReasoningDurationMs === 0) return true
  // Done thinking: use toggle
  return reasoningManuallyOpen.value
}
function toggleReasoning(): void {
  reasoningManuallyOpen.value = !reasoningManuallyOpen.value
}

watch(() => store.prdReasoningContent, () => {
  nextTick(() => {
    if (reasoningRef.value) reasoningRef.value.scrollTop = reasoningRef.value.scrollHeight
  })
})

function formatDuration(ms: number): string {
  if (!ms) return ''
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

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
  <div class="flex-1 flex flex-col overflow-hidden">
    <!-- Thinking process: auto-expand while thinking, collapsed after done -->
    <div v-if="store.prdReasoningContent" class="border-b border-gray-200 bg-gray-50 shrink-0">
      <button
        class="flex items-center gap-1 px-4 py-1.5 text-xs text-gray-500 hover:text-gray-700 w-full text-left"
        @click="toggleReasoning"
      >
        <span>{{ isReasoningOpen() ? '▾' : '▸' }}</span>
        <span class="font-medium">思考过程</span>
        <span v-if="store.prdReasoningDurationMs" class="text-gray-400 ml-1">
          ({{ formatDuration(store.prdReasoningDurationMs) }})
        </span>
        <span v-else class="text-blue-500 animate-pulse ml-1">思考中...</span>
      </button>
      <div
        v-if="isReasoningOpen()"
        ref="reasoningRef"
        class="px-4 py-2 text-xs text-gray-500 whitespace-pre-wrap max-h-[200px] overflow-y-auto border-t border-gray-100"
      >
        {{ store.prdReasoningContent }}
      </div>
    </div>

    <!-- PRD Document: fixed height, scroll overflow -->
    <StreamDocument
      :content="store.docStreamingContent"
      :is-streaming="store.docIsStreaming || store.isStreaming"
      language="md"
    />

    <!-- Export button -->
    <div v-if="!store.isStreaming && store.docStreamingContent" class="flex gap-2 px-4 py-2 border-t border-gray-200 bg-white shrink-0">
      <button
        class="px-3 py-1 text-sm border rounded hover:bg-gray-50 transition-colors"
        @click="handleExport"
      >
        📥 导出 MD
      </button>
    </div>
  </div>
</template>
