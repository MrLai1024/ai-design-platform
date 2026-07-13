<template>
  <div class="bg-white rounded-lg border p-4 h-full overflow-auto">
    <div class="prose prose-sm max-w-none" v-html="renderedContent" />
    <div v-if="isStreaming" class="text-blue-500 text-sm mt-2">▊ 生成中...</div>
    <div v-if="!isStreaming && content" class="flex gap-2 mt-4 pt-3 border-t">
      <button class="px-3 py-1 text-sm border rounded hover:bg-gray-50" @click="emit('edit')">📝 编辑补充</button>
      <button class="px-3 py-1 text-sm border rounded hover:bg-gray-50" @click="emit('next')">🔀 进入详细设计</button>
      <button class="px-3 py-1 text-sm border rounded hover:bg-gray-50" @click="emit('export')">📥 导出</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useGenerationStore } from '@/stores/generation'

defineEmits<{ 'edit': []; 'next': []; 'export': [] }>()
const store = useGenerationStore()
const content = computed(() => store.prdStreamingContent)
const isStreaming = computed(() => store.isStreaming)

const renderedContent = computed(() => {
  const c = content.value
  return c
    .replace(/### (.*)/g, '<h3 class="text-lg font-medium mt-4 mb-1">$1</h3>')
    .replace(/## (.*)/g, '<h2 class="text-xl font-bold mt-5 mb-2">$1</h2>')
    .replace(/# (.*)/g, '<h1 class="text-2xl font-bold mt-6 mb-3">$1</h1>')
    .replace(/- (.*)/g, '<li class="ml-4 text-sm">$1</li>')
    .replace(/\n\n/g, '<br/><br/>')
})
</script>
