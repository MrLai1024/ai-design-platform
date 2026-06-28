<!-- src/views/GenerationView.vue -->
<script setup lang="ts">
import { onMounted } from 'vue'
import { useGenerationStore } from '@/stores/generation'
import { useCodeParser } from '@/composables/useCodeParser'
import ChatPanel from '@/components/ChatPanel.vue'
import CodeEditor from '@/components/CodeEditor.vue'
import PreviewFrame from '@/components/PreviewFrame.vue'

const store = useGenerationStore()
// 启动 composable 的 watcher
useCodeParser()

onMounted(() => {
  store.resetAll()
})
</script>

<template>
  <div class="generation-view flex h-[calc(100vh-80px)]">
    <!-- 左侧：聊天面板 30% -->
    <div class="w-[30%] min-w-[300px] border-r border-gray-200">
      <ChatPanel />
    </div>

    <!-- 中间：代码编辑 35% -->
    <div class="w-[35%] min-w-[350px] border-r border-gray-200">
      <CodeEditor />
    </div>

    <!-- 右侧：预览 35% -->
    <div class="flex-1 min-w-[350px]">
      <PreviewFrame />
    </div>
  </div>
</template>
