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

      <!-- 工程文件 tab: 三栏 -->
      <div v-show="currentTab === 'files'" class="absolute inset-0 flex overflow-hidden">
        <!-- 左: AgentLog 35% -->
        <div class="w-[35%] min-w-[280px] border-r border-gray-200 flex flex-col">
          <AgentLog
            :entries="store.agentLogEntries"
            :is-streaming="store.isStreaming"
            @entry-click="onAgentLogClick"
          />
        </div>

        <!-- 右: FileExplorer (FileTree + CodeView) 65% -->
        <div class="flex-1">
          <FileExplorer />
        </div>
      </div>
    </div>
  </div>
</template>
