<!-- src/components/ChatPanel.vue -->
<script setup lang="ts">
import { ref, watch, nextTick, computed } from 'vue'
import { useGenerationStore } from '@/stores/generation'
import { useMultiAgent } from '@/composables/useMultiAgent'
import ChatInput from './ChatInput.vue'
import type { ComponentLibrary } from '@/types/generation'

const store = useGenerationStore()
const {
  startAnalysis,
  continueAnalysis,
  confirmAnalysis,
  confirmDesign,
  cancel: cancelAgent,
  isTransitioning,
  isCurrentStageFinished,
} = useMultiAgent()

const messagesContainer = ref<HTMLElement | null>(null)

// 自动滚到底部
watch(
  () => store.lastAssistantMessage?.content,
  async () => {
    await nextTick()
    if (messagesContainer.value) {
      messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
    }
  },
)

// 是否可以确认当前阶段（需求分析/设计阶段完成且不在流式中）
const canConfirm = computed(() => {
  const stage = store.stage
  if (stage !== 'analysis' && stage !== 'design') return false
  return isCurrentStageFinished()
})

// 按钮文案
const confirmLabel = computed(() => {
  if (store.stage === 'analysis') return '确认需求 → 进入详细设计'
  if (store.stage === 'design') return '确认方案 → 进入代码实现'
  return '确认'
})

function handleSend(content: string, lib: ComponentLibrary): void {
  if (store.stage === 'idle' || store.stage === 'analysis') {
    if (store.stage === 'idle') {
      startAnalysis(content, lib)
    } else {
      continueAnalysis(content)
    }
  }
}

function handleConfirm(): void {
  if (store.stage === 'analysis') {
    confirmAnalysis()
  } else if (store.stage === 'design') {
    confirmDesign()
  }
}

// 阶段标签
function stageLabel(stage?: string): string {
  const map: Record<string, string> = {
    analysis: '需求分析',
    design: '详细设计',
    code: '代码实现',
  }
  return stage ? map[stage] || '' : ''
}

function stageBadgeClass(stage?: string): string {
  switch (stage) {
    case 'analysis': return 'bg-purple-100 text-purple-700'
    case 'design': return 'bg-orange-100 text-orange-700'
    case 'code': return 'bg-green-100 text-green-700'
    default: return 'bg-gray-100 text-gray-500'
  }
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
          <!-- 阶段标签 + 流式指示器 -->
          <div v-if="msg.stage" class="flex items-center gap-2 mb-1">
            <span class="text-[10px] px-1.5 py-0.5 rounded-full font-medium" :class="stageBadgeClass(msg.stage)">
              {{ stageLabel(msg.stage) }}
            </span>
            <span
              v-if="msg.isStreaming"
              class="text-[10px] text-blue-500 animate-pulse"
            >
              生成中...
            </span>
          </div>

          <!-- 文本内容 -->
          <div v-if="msg.role === 'user'">{{ msg.content }}</div>
          <div
            v-else
            class="message-content prose prose-sm max-w-none"
            v-html="msg.content
              .replace(/```[\s\S]*?```/g, '')
              .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
              .replace(/\n/g, '<br>')
            "
          />

          <!-- 代码生成卡片 -->
          <div
            v-if="msg.role === 'assistant' && msg.codeBlocks.length > 0"
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

      <!-- 确认推进按钮 -->
      <div v-if="canConfirm" class="flex justify-center">
        <button
          class="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors"
          :disabled="isTransitioning"
          @click="handleConfirm"
        >
          <span v-if="isTransitioning" class="inline-flex items-center gap-1">
            <span class="animate-spin">⏳</span> 推进中...
          </span>
          <span v-else>{{ confirmLabel }}</span>
        </button>
      </div>
    </div>

    <ChatInput
      :is-streaming="store.isStreaming"
      :current-lib="store.currentLib"
      :current-stage="store.stage"
      @send="handleSend"
      @cancel="cancelAgent"
      @update:current-lib="store.setCurrentLib($event)"
    />
  </div>
</template>
