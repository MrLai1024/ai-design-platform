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
