<!-- src/components/FileTabBar.vue -->
<script setup lang="ts">
import type { FileEntry } from '@/types/generation'

defineProps<{
  files: FileEntry[]
  activeFile: string | null
}>()

const emit = defineEmits<{
  select: [filename: string]
  close: [filename: string]
  add: []
}>()
</script>

<template>
  <div class="file-tab-bar flex items-center bg-gray-100 border-b border-gray-200 overflow-x-auto">
    <button
      v-for="file in files"
      :key="file.filename"
      @click="emit('select', file.filename)"
      :class="[
        'flex items-center gap-1.5 px-3 py-1.5 text-xs border-r border-gray-200 whitespace-nowrap transition-colors',
        activeFile === file.filename
          ? 'bg-white text-blue-600 border-t-2 border-t-blue-600'
          : 'bg-transparent text-gray-600 hover:bg-gray-50',
      ]"
    >
      <span class="font-mono">{{ file.filename }}</span>
      <span v-if="file.isDirty" class="w-2 h-2 rounded-full bg-orange-400" title="未保存的更改" />
      <button
        @click.stop="emit('close', file.filename)"
        class="ml-1 text-gray-400 hover:text-red-500 text-lg leading-none"
        title="关闭文件"
      >
        &times;
      </button>
    </button>
    <button
      @click="emit('add')"
      class="px-3 py-1.5 text-xs text-gray-500 hover:text-blue-600 hover:bg-gray-50 border-r border-gray-200 transition-colors"
      title="新建文件"
    >
      +
    </button>
  </div>
</template>
