<!-- src/components/CodeEditor.vue -->
<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'
import { useGenerationStore } from '@/stores/generation'
import FileTabBar from './FileTabBar.vue'

const store = useGenerationStore()
const editorContainer = ref<HTMLElement | null>(null)
let editor: import('monaco-editor').editor.IStandaloneCodeEditor | null = null

// 懒加载 Monaco
onMounted(async () => {
  if (!editorContainer.value) return
  const monaco = await import('monaco-editor')
  editor = monaco.editor.create(editorContainer.value, {
    value: store.activeFileEntry?.content || '',
    language: 'html', // Vue SFC 使用 HTML 语法高亮
    theme: 'vs',
    minimap: { enabled: false },
    fontSize: 13,
    lineNumbers: 'on',
    scrollBeyondLastLine: false,
    wordWrap: 'on',
    automaticLayout: true,
    tabSize: 2,
  })

  editor.onDidChangeModelContent(() => {
    if (!store.activeFile || !editor) return
    const value = editor.getValue()
    store.updateFileContent(store.activeFile, value)
  })

  // 初始内容
  if (store.activeFileEntry) {
    editor.setValue(store.activeFileEntry.content)
  }
})

// 切换文件时更新编辑器内容
watch(
  () => store.activeFile,
  () => {
    if (!editor || !store.activeFileEntry) return
    const model = editor.getModel()
    if (model) {
      model.setValue(store.activeFileEntry.content)
    }
  },
)

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
    <div
      ref="editorContainer"
      class="flex-1 relative"
    />
    <div v-if="!store.activeFile" class="flex-1 flex items-center justify-center text-gray-400 text-sm">
      暂无文件 — 通过 AI 对话生成代码，或点击 + 新建
    </div>
  </div>
</template>
