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

// ── 选项解析与交互 ──

interface ParsedQuestion {
  question: string
  options: string[]
}

/** 从消息内容中解析问题和选项（**问题：** ... - option） */
function parseQuestion(content: string): ParsedQuestion | null {
  // 匹配 **问题：**<问题文本> 后跟 - 选项列表
  const match = content.match(/\*\*问题：\*\*\s*(.+?)((?:\n- [^\n]+)+)/s)
  if (!match || !match[1] || !match[2]) return null

  const question = match[1].trim()
  const options = match[2]
    .split('\n')
    .filter((line) => /^- /.test(line))
    .map((line) => line.replace(/^- /, '').trim())
    .filter(Boolean)

  if (options.length === 0) return null
  return { question, options }
}

/** 从内容中移除选项列表部分，得到纯文本 */
function stripOptions(content: string): string {
  // 移除 - 选项列表（**问题：** 之后的 - 行）
  const idx = content.indexOf('**问题：**')
  if (idx === -1) return content

  const before = content.slice(0, idx)
  const after = content.slice(idx)
  // 保留问题文本但去掉选项行
  const cleaned = after.replace(/\n- [^\n]+/g, '').replace(/\n- [^\n]+/g, '')
  return (before + cleaned).trim()
}

/** 判断消息是否有可交互的选项（最后一条 assistant 消息，流式结束，有选项） */
const interactiveOptions = computed<ParsedQuestion | null>(() => {
  const last = store.lastAssistantMessage
  if (!last || last.role !== 'assistant' || last.isStreaming) return null
  // 只在需求分析阶段且非 id 为 null 的情况
  if (store.stage !== 'analysis') return null
  return parseQuestion(last.content)
})

function handleOptionClick(option: string): void {
  if (store.isStreaming) return
  // 将选项文本作为用户回复发送
  continueAnalysis(option)
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

// 思考内容展开/折叠状态
const reasoningOpen = ref<Record<string, boolean>>({})

function toggleReasoning(msgId: string): void {
  reasoningOpen.value[msgId] = !reasoningOpen.value[msgId]
}

function formatDuration(ms?: number): string {
  if (!ms) return ''
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
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

          <!-- 思考内容（可折叠） -->
          <div
            v-if="msg.role === 'assistant' && msg.reasoningContent"
            class="mb-2"
          >
            <button
              class="flex items-center gap-1 text-[10px] text-gray-500 hover:text-gray-700 transition-colors"
              @click="toggleReasoning(msg.id)"
            >
              <span>{{ reasoningOpen[msg.id] ? '▾' : '▸' }}</span>
              <span>思考过程</span>
              <span v-if="msg.reasoningDurationMs" class="text-gray-400">
                ({{ formatDuration(msg.reasoningDurationMs) }})
              </span>
            </button>
            <div
              v-if="reasoningOpen[msg.id]"
              class="mt-1 p-2 bg-gray-50 border border-gray-200 rounded text-xs text-gray-500 whitespace-pre-wrap max-h-[200px] overflow-y-auto"
            >
              {{ msg.reasoningContent }}
            </div>
          </div>

          <!-- 文本内容 -->
          <div v-if="msg.role === 'user'">{{ msg.content }}</div>
          <div
            v-else
            class="message-content prose prose-sm max-w-none"
            v-html="stripOptions(msg.content)
              .replace(/```[\s\S]*?```/g, '')
              .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
              .replace(/\n/g, '<br>')
            "
          />

          <!-- 选项按钮（最后一条 assistant 消息，流式结束，有可交互选项） -->
          <div
            v-if="msg === store.lastAssistantMessage && interactiveOptions"
            class="mt-2 space-y-1"
          >
            <div class="text-[10px] text-gray-400 mb-1">点击选择：</div>
            <button
              v-for="(opt, i) in interactiveOptions.options"
              :key="i"
              class="block w-full text-left px-3 py-1.5 text-xs border border-blue-200 rounded-lg bg-blue-50 text-blue-700 hover:bg-blue-100 hover:border-blue-300 transition-colors"
              :disabled="store.isStreaming"
              @click="handleOptionClick(opt)"
            >
              {{ opt }}
            </button>
          </div>

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
