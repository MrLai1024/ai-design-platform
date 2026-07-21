<!-- src/components/ChatPanel.vue -->
<script setup lang="ts">
import { ref, watch, nextTick, computed } from 'vue'
import { useGenerationStore } from '@/stores/generation'
import { useMultiAgent } from '@/composables/useMultiAgent'
import { useStreamChat } from '@/composables/useStreamChat'
import ChatInput from './ChatInput.vue'

const store = useGenerationStore()
const {
  startGeneration,
  startGraphGeneration,
  confirmStage,
  cancel: cancelAgent,
  isTransitioning,
} = useMultiAgent()
const { send: sendStream } = useStreamChat()

// 需求分析阶段的 system prompt（后端 LangGraph 节点的镜像）
const ANALYSIS_SYSTEM_PROMPT = `你是一个资深产品需求分析师。你的职责是**澄清需求**，不是写代码或设计方案。

## 核心规则（必须严格遵守）
1. **绝对禁止**编写代码、组件名、技术方案
2. **绝对禁止**输出设计方案、组件树、数据流
3. **只能**做需求澄清：通过提问逐步明确用户想要什么

## 工作流程
用户的需求通常比较模糊。你需要通过多轮提问来明确功能边界、页面布局、交互行为、数据内容。

**每轮只问一个问题**，给出 2-4 个具体选项让用户选择。

输出格式（提问阶段）：
**问题：** <一个问题>
- <选项A>
- <选项B>
- <选项C>

当你认为信息已经足够（通常 3+ 轮 Q&A），输出：
**准备就绪！** 请点击下方的「🚀 开始设计」按钮，我将为你生成完整的需求规格文档。

注意：你绝对不能自己输出需求规格文档，PRD 将由后续流程生成。`

const messagesContainer = ref<HTMLElement | null>(null)

// Auto-scroll to bottom on any message change during streaming
function scrollChatToBottom(): void {
  nextTick(() => {
    if (messagesContainer.value) {
      messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
    }
  })
}

// Scroll reasoning content div to bottom
function scrollReasoningToBottom(): void {
  nextTick(() => {
    const el = messagesContainer.value?.querySelector('.reasoning-content:last-child')
    if (el) el.scrollTop = el.scrollHeight
  })
}

watch(() => store.messages.length, scrollChatToBottom)
watch(() => store.lastAssistantMessage?.content, scrollChatToBottom)
watch(() => store.lastAssistantMessage?.reasoningContent, () => {
  scrollChatToBottom()
  scrollReasoningToBottom()
})

// 判断当前阶段是否完成
function isCurrentStageFinished(): boolean {
  if (store.isStreaming) return false
  const last = store.lastAssistantMessage
  if (!last || last.isStreaming) return false
  return last.content.length > 0 || (last.reasoningContent?.length ?? 0) > 0
}

// 反问完成后显示"开始设计"按钮
const canStartDesign = computed(() => {
  if (store.stage !== 'analysis') return false
  if (store.stagePhase !== 'qa' && store.stagePhase !== 'idle') return false
  return isCurrentStageFinished() && store.messages.length >= 2
})

async function continueAnalysis(userContent: string): Promise<void> {
  await sendStream({
    content: userContent,
    lib: store.currentLib,
    stage: 'analysis',
    systemPrompt: ANALYSIS_SYSTEM_PROMPT,
  })
}

function handleSend(content: string): void {
  if (store.stage === 'idle' || store.stage === 'analysis') {
    if (store.stage === 'idle') {
      startGeneration(content, store.currentLib, ANALYSIS_SYSTEM_PROMPT)
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

async function handleStartDesign(): Promise<void> {
  // Collect the user's original requirement from first message
  const firstUserMsg = store.messages.find(m => m.role === 'user')
  const requirement = firstUserMsg?.content || ''
  await startGraphGeneration(requirement, store.currentLib)
}

// 阶段标签
function stageLabel(stage?: string): string {
  const map: Record<string, string> = {
    analysis: '需求分析',
    design: '详细设计',
    code: '功能开发',
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
  reasoningOpen.value[msgId] = !isReasoningOpen(msgId)
}

/** Auto-expand while thinking (isStreaming=true, has reasoning content, no duration yet).
 *  After thinking done (duration > 0), user controls via toggle. */
function isReasoningOpen(msgId: string): boolean {
  const msg = store.messages.find(m => m.id === msgId)
  if (!msg) return false
  // Still thinking: auto-expand
  if (msg.isStreaming && msg.reasoningContent && !msg.reasoningDurationMs) return true
  // Thinking done: use user toggle state
  return reasoningOpen.value[msgId] ?? false
}

function formatDuration(ms?: number): string {
  if (!ms) return ''
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}
</script>

<template>
  <div class="chat-panel flex flex-col h-full bg-white">
    <div ref="messagesContainer" class="flex-1 overflow-y-auto px-4 py-3 space-y-4">
      <div v-if="store.messages.length === 0" class="text-center text-gray-400 mt-8">
        <p class="text-lg mb-2">👋 描述你的需求</p>
        <p class="text-xs">例如："生成XX系统;实现XX功能需求"</p>
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
              <span>{{ isReasoningOpen(msg.id) ? '▾' : '▸' }}</span>
              <span>思考过程</span>
              <span v-if="msg.reasoningDurationMs" class="text-gray-400">
                ({{ formatDuration(msg.reasoningDurationMs) }})
              </span>
            </button>
            <div
              v-if="isReasoningOpen(msg.id)"
              class="reasoning-content mt-1 p-2 bg-gray-50 border border-gray-200 rounded text-xs text-gray-500 whitespace-pre-wrap max-h-[200px] overflow-y-auto"
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

      <!-- 开始设计按钮（反问完成时显示） -->
      <div v-if="canStartDesign" class="flex justify-center pb-2">
        <button
          class="px-4 py-2 bg-green-600 text-white rounded-lg text-sm font-medium hover:bg-green-700 disabled:opacity-50 transition-colors"
          :disabled="isTransitioning"
          @click="handleStartDesign"
        >
          <span v-if="isTransitioning" class="inline-flex items-center gap-1">
            <span class="animate-spin">⏳</span> 启动中...
          </span>
          <span v-else>🚀 开始设计</span>
        </button>
      </div>
    </div>

    <ChatInput
      :is-streaming="store.isStreaming"
      :current-stage="store.stage"
      @send="handleSend"
      @cancel="cancelAgent"
    />
  </div>
</template>
