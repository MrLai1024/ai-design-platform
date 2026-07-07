<!-- src/components/FileExplorer.vue -->
<script setup lang="ts">
import { ref, computed } from 'vue'
import { useGenerationStore } from '@/stores/generation'
import type { FileEntry } from '@/types/generation'

const store = useGenerationStore()
const selectedFile = ref<string | null>(null)

const fileEntries = computed(() => {
  return Array.from(store.files.values())
})

// 分组：按目录
const fileTree = computed(() => {
  const tree: Record<string, FileEntry[]> = {}
  for (const entry of fileEntries.value) {
    const dir = entry.filename.includes('/')
      ? entry.filename.substring(0, entry.filename.lastIndexOf('/'))
      : '/'
    if (!tree[dir]) tree[dir] = []
    tree[dir]!.push(entry)
  }
  return tree
})

const currentFile = computed(() => {
  if (!selectedFile.value) return null
  return store.files.get(selectedFile.value) ?? null
})

function selectFile(filename: string): void {
  selectedFile.value = filename
}

// Default to first file when files become available
if (fileEntries.value.length > 0 && !selectedFile.value) {
  selectedFile.value = fileEntries.value[0]!.filename
}
</script>

<template>
  <div class="file-explorer flex h-full bg-white">
    <!-- 左侧文件树 -->
    <div class="w-[200px] min-w-[160px] border-r border-gray-200 overflow-y-auto bg-gray-50">
      <div v-for="(entries, dir) in fileTree" :key="dir">
        <div
          v-if="dir !== '/'"
          class="px-3 py-1.5 text-xs text-gray-500 font-medium uppercase tracking-wide"
        >
          {{ dir }}
        </div>
        <div
          v-for="entry in entries"
          :key="entry.filename"
          class="px-3 py-1.5 text-xs cursor-pointer flex items-center gap-1.5 hover:bg-gray-100 transition-colors"
          :class="{
            'bg-blue-50 text-blue-700 font-medium': selectedFile === entry.filename,
            'text-gray-700': selectedFile !== entry.filename,
          }"
          @click="selectFile(entry.filename)"
        >
          <span
            class="font-mono"
            :class="{
              'text-green-600': entry.language === 'vue',
              'text-blue-600': entry.language === 'typescript',
              'text-yellow-600': entry.language === 'javascript',
              'text-pink-600': entry.language === 'css',
              'text-gray-600': !['vue','typescript','javascript','css'].includes(entry.language),
            }"
          >●</span>
          <span class="truncate font-mono">{{ entry.filename.split('/').pop() }}</span>
        </div>
      </div>

      <div v-if="fileEntries.length === 0" class="p-4 text-center text-gray-400 text-xs">
        暂无文件 — 等待代码生成
      </div>
    </div>

    <!-- 右侧代码查看器 -->
    <div class="flex-1 overflow-y-auto bg-[#1e1e2e]">
      <div v-if="currentFile" class="p-4">
        <div class="text-xs text-gray-400 mb-2 font-mono">
          {{ currentFile.filename }}
          <span
            class="ml-2"
            :class="{
              'text-green-400': currentFile.language === 'vue',
              'text-blue-400': currentFile.language === 'typescript',
              'text-yellow-400': currentFile.language === 'javascript',
              'text-pink-400': currentFile.language === 'css',
            }"
          >
            ({{ currentFile.language }})
          </span>
        </div>
        <pre class="text-sm text-gray-200 font-mono whitespace-pre-wrap"><code>{{ currentFile.content }}</code></pre>
      </div>
      <div v-else class="p-4 text-center text-gray-500 text-sm">
        选择文件查看代码
      </div>
    </div>
  </div>
</template>
