<!-- src/components/ChatInput.vue -->
<script setup lang="ts">
import { ref, computed } from 'vue'
import type { Stage } from '@/types/generation'

const emit = defineEmits<{
  send: [content: string]
  cancel: []
}>()

const props = defineProps<{
  isStreaming: boolean
  currentStage: Stage
}>()

const inputText = ref('')

const placeholder = computed(() => {
  switch (props.currentStage) {
    case 'analysis': return '回答需求分析师的问题，或补充需求细节...'
    case 'design': return '对设计方案有修改意见？在这里补充...'
    case 'code': return '对生成的代码有调整要求？在这里说明...'
    default: return '描述你的需求...'
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
  emit('send', text)
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
