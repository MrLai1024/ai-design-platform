<!-- src/components/ChatInput.vue -->
<script setup lang="ts">
import { ref } from 'vue'
import type { ComponentLibrary } from '@/types/generation'

const emit = defineEmits<{
  send: [content: string, lib: ComponentLibrary]
  cancel: []
  'update:currentLib': [lib: ComponentLibrary]
}>()

const props = defineProps<{
  isStreaming: boolean
  currentLib: ComponentLibrary
}>()

const inputText = ref('')
const LIB_OPTIONS: Array<{ key: ComponentLibrary; label: string }> = [
  { key: 'tailwind', label: 'Tailwind CSS' },
  { key: 'antd', label: 'Ant Design Vue' },
  { key: 'element', label: 'Element Plus' },
  { key: 'echarts', label: 'ECharts' },
]

function handleSend(): void {
  const text = inputText.value.trim()
  if (!text || props.isStreaming) return
  emit('send', text, props.currentLib)
  inputText.value = ''
}

function handleKeydown(e: KeyboardEvent): void {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  }
}
</script>

<template>
  <div class="chat-input border-t border-gray-200 p-4 bg-white">
    <div class="flex items-center gap-2 mb-2">
      <select
        :value="currentLib"
        @change="$emit('update:currentLib', ($event.target as HTMLSelectElement).value as ComponentLibrary)"
        class="text-xs border border-gray-300 rounded px-2 py-1 bg-white text-gray-600"
      >
        <option v-for="opt in LIB_OPTIONS" :key="opt.key" :value="opt.key">
          {{ opt.label }}
        </option>
      </select>
    </div>
    <div class="flex gap-2">
      <textarea
        v-model="inputText"
        @keydown="handleKeydown"
        :disabled="isStreaming"
        placeholder="描述你想要生成的组件..."
        rows="2"
        class="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:bg-gray-100"
      />
      <button
        v-if="!isStreaming"
        @click="handleSend"
        :disabled="!inputText.trim()"
        class="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        发送
      </button>
      <button
        v-else
        @click="$emit('cancel')"
        class="px-4 py-2 bg-red-600 text-white rounded-lg text-sm font-medium hover:bg-red-700 transition-colors"
      >
        取消
      </button>
    </div>
  </div>
</template>
