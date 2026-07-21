<!-- src/components/DesignStagePanel.vue -->
<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'
import { useGenerationStore } from '@/stores/generation'
import StreamDocument from './StreamDocument.vue'

const store = useGenerationStore()
const reasoningRef = ref<HTMLElement | null>(null)
const reasoningManuallyOpen = ref(true)

function isReasoningOpen(): boolean {
  if (store.prdReasoningContent && store.prdReasoningDurationMs === 0) return true
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
</script>

<template>
  <div class="flex-1 flex flex-col overflow-hidden">
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

    <StreamDocument
      :content="store.docStreamingContent"
      :is-streaming="store.docIsStreaming || store.isStreaming"
      language="md"
    />
  </div>
</template>
