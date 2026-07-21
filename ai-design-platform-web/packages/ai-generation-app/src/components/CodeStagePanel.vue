<!-- src/components/CodeStagePanel.vue -->
<script setup lang="ts">
import { useGenerationStore } from '@/stores/generation'
import TabBar from './TabBar.vue'
import PreviewFrame from './PreviewFrame.vue'
import FileExplorer from './FileExplorer.vue'
import ToolTracePanel from './ToolTracePanel.vue'

const store = useGenerationStore()

const codeTabs = [
  { key: 'preview' as const, label: '实时预览' },
  { key: 'files' as const, label: '工程文件' },
  { key: 'trace' as const, label: 'Tool Trace' },
]

function handleTabSelect(key: string): void {
  store.setCodeViewTab(key as 'preview' | 'files')
}
</script>

<template>
  <div class="flex-1 flex flex-col">
    <TabBar
      :tabs="codeTabs"
      :active-tab="store.codeViewTab === 'trace' ? 'trace' : store.codeViewTab === 'files' ? 'files' : 'preview'"
      @select="handleTabSelect"
    />
    <div class="flex-1 relative">
      <div v-show="store.codeViewTab === 'preview'" class="absolute inset-0">
        <PreviewFrame />
      </div>
      <div v-show="store.codeViewTab === 'files'" class="absolute inset-0">
        <FileExplorer />
      </div>
      <div v-show="store.codeViewTab === 'trace'" class="absolute inset-0">
        <ToolTracePanel />
      </div>
    </div>
  </div>
</template>
