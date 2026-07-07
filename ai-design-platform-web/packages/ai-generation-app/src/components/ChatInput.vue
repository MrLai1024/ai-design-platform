<!-- src/components/ChatInput.vue -->
<script setup lang="ts">
import { ref, computed } from 'vue'
import type { ComponentLibrary, Stage } from '@/types/generation'

const emit = defineEmits<{
  send: [content: string, lib: ComponentLibrary]
  cancel: []
  'update:currentLib': [lib: ComponentLibrary]
}>()

const props = defineProps<{
  isStreaming: boolean
  currentLib: ComponentLibrary
  currentStage: Stage
}>()

const inputText = ref('')
const LIB_OPTIONS: Array<{ key: ComponentLibrary; label: string }> = [
  { key: 'tailwind', label: 'Tailwind CSS' },
  { key: 'antd', label: 'Ant Design Vue' },
  { key: 'element', label: 'Element Plus' },
  { key: 'echarts', label: 'ECharts' },
]

const placeholder = computed(() => {
  switch (props.currentStage) {
    case 'analysis': return '回答需求分析师的问题，或补充需求细节...'
    case 'design': return '对设计方案有修改意见？在这里补充...'
    case 'code': return '对生成的代码有调整要求？在这里说明...'
    default: return '描述你想要生成的组件...'
  }
})

const sendLabel = computed(() => {
  switch (props.currentStage) {
    case 'analysis': return '回复'
    case 'design': return '补充'
    case 'code': return '调整'
    default: return '发送'
  }
})

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
        :disabled="currentStage !== 'idle'"
        @change="$emit('update:currentLib', ($event.target as HTMLSelectElement).value as ComponentLibrary)"
        class="text-xs border border-gray-300 rounded px-2 py-1 bg-white text-gray-600 disabled:opacity-50 disabled:cursor-not-allowed"
        :title="currentStage !== 'idle' ? '组件库仅在初始阶段可选' : ''"
      >
        <option v-for="opt in LIB_OPTIONS" :key="opt.key" :value="opt.key">
          {{ opt.label }}
        </option>
      </select>
      <span
        v-if="currentStage !== 'idle'"
        class="text-[10px] px-1.5 py-0.5 rounded-full font-medium"
        :class="{
          'bg-purple-100 text-purple-700': currentStage === 'analysis',
          'bg-orange-100 text-orange-700': currentStage === 'design',
          'bg-green-100 text-green-700': currentStage === 'code',
        }"
      >
        {{ currentStage === 'analysis' ? '需求分析中' : currentStage === 'design' ? '详细设计中' : '代码实现中' }}
      </span>
    </div>
    <div class="flex gap-2">
      <textarea
        v-model="inputText"
        @keydown="handleKeydown"
        :disabled="isStreaming"
        :placeholder="placeholder"
        rows="2"
        class="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:bg-gray-100"
      />
      <button
        v-if="!isStreaming"
        @click="handleSend"
        :disabled="!inputText.trim()"
        class="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        {{ sendLabel }}
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
