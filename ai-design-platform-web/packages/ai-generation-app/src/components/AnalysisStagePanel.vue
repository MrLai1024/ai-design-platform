<!-- src/components/AnalysisStagePanel.vue -->
<script setup lang="ts">
import { ref } from 'vue'
import { useGenerationStore } from '@/stores/generation'
import StreamDocument from './StreamDocument.vue'

const store = useGenerationStore()
const reasoningOpen = ref(true)

function toggleReasoning(): void {
  reasoningOpen.value = !reasoningOpen.value
}

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
  <div class="flex-1 flex flex-col">
    <!-- Thinking process (collapsible, like ChatPanel) -->
    <div v-if="store.prdReasoningContent" class="border-b border-gray-200 bg-gray-50">
      <button
        class="flex items-center gap-1 px-4 py-1.5 text-xs text-gray-500 hover:text-gray-700 w-full text-left"
        @click="toggleReasoning"
      >
        <span>{{ reasoningOpen ? '▾' : '▸' }}</span>
        <span>思考过程</span>
        <span v-if="store.prdReasoningDurationMs" class="text-gray-400">
          ({{ formatDuration(store.prdReasoningDurationMs) }})
        </span>
      </button>
      <div
        v-if="reasoningOpen"
        class="px-4 py-2 text-xs text-gray-500 whitespace-pre-wrap max-h-[200px] overflow-y-auto border-t border-gray-100"
      >
        {{ store.prdReasoningContent }}
      </div>
    </div>

    <!-- PRD Document -->
    <StreamDocument
      :content="store.docStreamingContent"
      :is-streaming="store.docIsStreaming || store.isStreaming"
      language="md"
    />

    <!-- Export button (shown after generation complete) -->
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
