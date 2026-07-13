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
