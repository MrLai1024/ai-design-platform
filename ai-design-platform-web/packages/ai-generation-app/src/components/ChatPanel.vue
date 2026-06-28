<!-- src/components/ChatPanel.vue -->
<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'
import { useGenerationStore } from '@/stores/generation'
import { useStreamChat } from '@/composables/useStreamChat'
import ChatInput from './ChatInput.vue'

const store = useGenerationStore()
const { send, cancel } = useStreamChat()
const messagesContainer = ref<HTMLElement | null>(null)

// 新消息时自动滚到底部
watch(
  () => store.messages.length,
  async () => {
    await nextTick()
    if (messagesContainer.value) {
      messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
    }
  },
)

// 流式内容更新时也滚动
watch(
  () => store.lastAssistantMessage?.content,
  async () => {
    await nextTick()
    if (messagesContainer.value) {
      messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
    }
  },
)

function handleSend(content: string, lib: Parameters<typeof send>[1]): void {
  send(content, lib)
}

function renderMessageContent(content: string): string {
  // 简单 markdown 渲染（代码块之外的内容）
  return content
    .replace(/```[\s\S]*?```/g, '') // 移除代码块（由代码卡片单独展示）
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\n/g, '<br>')
}

function hasCodeBlocks(msg: typeof store.messages[number]): boolean {
  return msg.codeBlocks.length > 0
}
</script>

<template>
  <div class="chat-panel flex flex-col h-full bg-white">
    <div class="px-4 py-3 border-b border-gray-200 bg-gray-50">
      <h2 class="text-sm font-semibold text-gray-700">AI 代码生成</h2>
    </div>

    <div ref="messagesContainer" class="flex-1 overflow-y-auto px-4 py-3 space-y-4">
      <div v-if="store.messages.length === 0" class="text-center text-gray-400 mt-8">
        <p class="text-lg mb-2">👋 描述你想要生成的组件</p>
        <p class="text-xs">例如："用表格展示用户列表，包含姓名、邮箱、状态列"</p>
      </div>

      <div
        v-for="msg in store.messages"
        :key="msg.id"
        :class="[
          'message flex',
          msg.role === 'user' ? 'justify-end' : 'justify-start',
        ]"
      >
        <div
          :class="[
            'max-w-[90%] rounded-lg px-4 py-2.5 text-sm',
            msg.role === 'user'
              ? 'bg-blue-600 text-white'
              : 'bg-gray-100 text-gray-800',
          ]"
        >
          <!-- 文本内容 -->
          <div v-if="msg.role === 'user'">{{ msg.content }}</div>
          <div
            v-else
            class="message-content prose prose-sm max-w-none"
            v-html="renderMessageContent(msg.content)"
          />

          <!-- 代码生成卡片 -->
          <div
            v-if="msg.role === 'assistant' && hasCodeBlocks(msg)"
            class="mt-2 pt-2 border-t border-gray-200"
          >
            <div class="text-xs text-gray-500 mb-1">生成了 {{ msg.codeBlocks.length }} 个文件：</div>
            <div class="flex flex-wrap gap-1">
              <span
                v-for="block in msg.codeBlocks"
                :key="block.filename"
                class="inline-block px-2 py-0.5 text-xs bg-blue-50 text-blue-700 rounded border border-blue-200 font-mono"
              >
                {{ block.filename }}
              </span>
            </div>
          </div>

          <!-- 流式输出指示器 -->
          <span
            v-if="msg.isStreaming && !msg.content"
            class="inline-block w-2 h-4 bg-gray-400 animate-pulse"
          />
        </div>
      </div>
    </div>

    <ChatInput
      :is-streaming="store.isStreaming"
      :current-lib="store.currentLib"
      @send="handleSend"
      @cancel="cancel"
      @update:current-lib="store.setCurrentLib($event)"
    />
  </div>
</template>
