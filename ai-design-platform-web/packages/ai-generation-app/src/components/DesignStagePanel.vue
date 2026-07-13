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
