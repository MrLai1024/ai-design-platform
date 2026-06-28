<!-- src/components/CodeEditor.vue -->
<script setup lang="ts">
import { watch } from 'vue'
import { useGenerationStore } from '@/stores/generation'
import FileTabBar from './FileTabBar.vue'

const store = useGenerationStore()

function onContentChange(e: Event): void {
  const value = (e.target as HTMLTextAreaElement).value
  if (store.activeFile) {
    store.updateFileContent(store.activeFile, value)
  }
}

function handleFileClose(filename: string): void {
  store.removeFile(filename)
}

function handleFileAdd(): void {
  const name = prompt('文件名（含 .vue 后缀）：', 'NewComponent.vue')
  if (!name) return
  const filename = name.endsWith('.vue') ? name : `${name}.vue`
  store.addNewFile(filename)
}
</script>

<template>
  <div class="code-editor flex flex-col h-full bg-white">
    <div class="px-4 py-2 border-b border-gray-200 bg-gray-50 flex items-center justify-between">
      <h2 class="text-sm font-semibold text-gray-700">代码编辑</h2>
      <span v-if="store.activeFile" class="text-xs text-gray-400 font-mono">
        {{ store.activeFile }}
        <span v-if="store.activeFileEntry?.source === 'ai'" class="text-blue-400">(AI 生成)</span>
        <span v-else class="text-green-400">(手动)</span>
      </span>
    </div>
    <FileTabBar
      :files="store.fileList"
      :active-file="store.activeFile"
      @select="store.setActiveFile"
      @close="handleFileClose"
      @add="handleFileAdd"
    />
    <textarea
      v-if="store.activeFileEntry"
      :value="store.activeFileEntry.content"
      @input="onContentChange"
      class="flex-1 w-full p-4 font-mono text-sm resize-none outline-none border-0 bg-gray-50 text-gray-800 leading-relaxed"
      placeholder="选择文件开始编辑..."
      spellcheck="false"
    />
    <div v-else class="flex-1 flex items-center justify-center text-gray-400 text-sm">
      暂无文件 — 通过 AI 对话生成代码，或点击 + 新建
    </div>
  </div>
</template>
