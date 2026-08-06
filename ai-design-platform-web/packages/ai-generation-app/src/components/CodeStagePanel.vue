<!-- src/components/CodeStagePanel.vue -->
<script setup lang="ts">
import { computed } from 'vue'
import { useGenerationStore } from '@/stores/generation'
import { useMultiAgent } from '@/composables/useMultiAgent'
import TabBar from './TabBar.vue'
import PreviewFrame from './PreviewFrame.vue'
import FileExplorer from './FileExplorer.vue'
import AgentLog from './AgentLog.vue'
import type { AgentLogEntry } from '@/types/generation'

const store = useGenerationStore()
const { sendFeedback, cancelGeneration } = useMultiAgent()

const currentTab = computed(() => store.codeViewTab === 'preview' ? 'preview' : 'files')

const codeTabs = [
  { key: 'files' as const, label: '工程文件' },
  { key: 'preview' as const, label: '实时预览' },
]

function handleTabSelect(key: string): void {
  store.setCodeViewTab(key as 'preview' | 'files')
}

function onAgentLogClick(entry: AgentLogEntry): void {
  const path = entry.filePath || entry.toolArgs?.path
  if (path && store.files.has(path)) {
    store.setActiveFile(path)
  }
}

function onSendFeedback(text: string): void {
  // Add feedback entry to AgentLog (10.2: 处置结果改由对话框 feedback_card 呈现)
  store.addAgentLogEntry({
    id: Date.now().toString(36) + Math.random().toString(36).slice(2, 7),
    type: 'feedback_summary',
    timestamp: Date.now(),
    feedbackText: text,
    feedbackResult: '处置结果见对话框卡片',
  })
  sendFeedback(text)
}

function onCancelGeneration(): void {
  cancelGeneration()
  store.addAgentLogEntry({
    id: Date.now().toString(36) + Math.random().toString(36).slice(2, 7),
    type: 'cancel',
    timestamp: Date.now(),
    summary: '用户手动终止',
  })
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
      <div v-show="currentTab === 'preview'" class="absolute inset-0">
        <PreviewFrame />
      </div>

      <div v-show="currentTab === 'files'" class="absolute inset-0 flex overflow-hidden">
        <div class="w-[35%] min-w-[280px] border-r border-gray-200 flex flex-col">
          <AgentLog
            :entries="store.agentLogEntries"
            :is-streaming="store.isStreaming"
            @entry-click="onAgentLogClick"
            @send-feedback="onSendFeedback"
            @cancel-generation="onCancelGeneration"
          />
        </div>
        <div class="flex-1">
          <FileExplorer />
        </div>
      </div>
    </div>
  </div>
</template>
