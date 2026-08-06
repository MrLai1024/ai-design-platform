<!-- src/components/ChatPanel.vue -->
<script setup lang="ts">
import { ref, watch, nextTick, computed } from 'vue'
import { useGenerationStore } from '@/stores/generation'
import { useMultiAgent } from '@/composables/useMultiAgent'
import { useStreamChat } from '@/composables/useStreamChat'
import ChatInput from './ChatInput.vue'
import ManagerCard from './ManagerCard.vue'
import type { ChatMessage } from '@/types/generation'

const store = useGenerationStore()
const {
  startBrainstorm,
  sendBrainstormTurn,
  startGraphGeneration,
  startIncrementalGeneration,
  regenIncrementalStep,
  confirmStage,
  forceResumeNextConfirm,
  sendFeedback,
  routeUserMessage,
  cancel: cancelAgent,
  isTransitioning,
} = useMultiAgent()
const { send: sendStream } = useStreamChat()

// 8.x 增量开发入口: 应用完成 (e2e 通过) 后可对当前应用发起增量开发,
// 用户在输入框键入新需求后发送。
const incrementalDraft = ref(false)
const canStartIncremental = computed(() =>
  store.stage === 'e2e' && store.stageStatus.e2e === 'done',
)

function handleStartIncremental(): void {
  incrementalDraft.value = true
}

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

// 头脑风暴阶段判定（任务组 3：澄清期间所有输入直接进 agenda 引擎，不做意图分类）
function isBrainstormActive(): boolean {
  return store.stage === 'analysis' && (store.stagePhase === 'qa' || store.stagePhase === 'idle')
}

// 头脑风暴收敛（覆盖度达标 + 用户确认）→ 显示"开始设计"按钮
// 必须仍在澄清阶段（stagePhase === 'qa'）：PRD 流式生成中（'generating'）
// 隐藏按钮，避免重点击中断在途生成（fix #3）
const canStartDesign = computed(() => {
  if (store.stage !== 'analysis') return false
  if (store.stagePhase !== 'qa') return false
  return store.brainstormConverged
})

/** 澄清阶段输入 → agenda 引擎（POST /api/v1/generation/brainstorm） */
async function continueBrainstorm(userContent: string, itemId?: string): Promise<void> {
  await sendBrainstormTurn(userContent, itemId)
}

/** 非头脑风暴阶段的兜底聊天回复（design/code 等阶段的自由输入） */
async function continueChat(userContent: string): Promise<void> {
  // useStreamChat 只接受 analysis/design/code 三档 stage，收窄类型（fix #12）
  const chatStage = store.stage === 'design' || store.stage === 'code'
    ? store.stage
    : 'analysis'
  await sendStream({
    content: userContent,
    stage: chatStage,
  })
}

async function handleSend(content: string): Promise<void> {
  // 8.x 增量开发：按钮触发后，下一次发送的内容作为新需求提交给增量流水线
  if (incrementalDraft.value) {
    incrementalDraft.value = false
    await startIncrementalGeneration(content)
    return
  }
  // 需求输入：全新开始 → 头脑风暴首轮（需求画像，任务组 3）
  if (store.stage === 'idle') {
    startBrainstorm(content)
    return
  }
  // 需求澄清 Q&A：走 agenda 引擎
  if (isBrainstormActive()) {
    continueBrainstorm(content)
    return
  }
  // 2.3: 流程进行中 → Manager 自判意图后分流
  const intent = await routeUserMessage(content)
  if (intent === 'reply_qa') {
    await continueChat(content)
  }
}

/** 卡片选项点击：question_card/proposal_card/confirm_card 在头脑风暴阶段走 agenda 引擎；diagnosis_card（求援）按选项分流 */
async function handleCardOptionClick(msg: ChatMessage, option: string): Promise<void> {
  if (store.isStreaming) return
  const card = msg.meta?.card
  if (card === 'question_card') {
    // 议程提问卡片：带 item_id 精准落回议程项
    continueBrainstorm(option, msg.meta?.data?.item_id as string | undefined)
  } else if (card === 'diagnosis_card') {
    if (option === '继续自主') {
      confirmStage(store.stage)
    } else if (option === '转人工') {
      store.setManualMode(true)
    }
  } else if (card === 'confirm_card' && (msg.meta?.data as any)?.scope_confirm) {
    // 9.3 (I5): 范围变更确认卡 — 「确认」→ resume (后端批准范围变更,
    // 进入重派反馈); 「重新生成」→ feedback (后端拒绝, 范围不变更)。
    // 10.1: 用户反馈引发的范围确认 — 处置挂起在当前 runner, 「确认」必须
    // resume 同一 runner (fresh-start 新 UUID 会丢失处置)。
    if (option === '确认') {
      forceResumeNextConfirm()
      confirmStage(store.stage)
    } else if (option === '重新生成') {
      await sendFeedback(option)
    }
  } else if (card === 'confirm_card' && option === '重新生成' && (msg.meta?.data as any)?.incremental) {
    // 8.x (review I1): 增量确认卡「重新生成」— 服务端清除当前级产物重算,
    // 不再静默跳过用户修正。
    await regenIncrementalStep()
  } else if (isBrainstormActive()) {
    // proposal_card（方案对比选择）/ confirm_card（收敛确认）→ agenda 引擎
    continueBrainstorm(option, msg.meta?.data?.item_id as string | undefined)
  } else {
    // 收敛后的流程卡片（coverage_matrix 等）→ Manager 意图路由兜底
    await routeUserMessage(option)
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
  // 旧消息的文本选项兜底：澄清阶段走 agenda 引擎，其他阶段走意图路由
  if (isBrainstormActive()) {
    continueBrainstorm(option)
  } else {
    routeUserMessage(option)
  }
}

async function handleStartDesign(): Promise<void> {
  // Collect the user's original requirement from first message
  const firstUserMsg = store.messages.find(m => m.role === 'user')
  const requirement = firstUserMsg?.content || ''
  await startGraphGeneration(requirement)
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

          <!-- Manager 结构化消息卡片（meta 驱动，任务组 2） -->
          <ManagerCard
            v-if="msg.meta"
            :meta="msg.meta"
            :disabled="store.isStreaming"
            @option-click="(opt: string) => handleCardOptionClick(msg, opt)"
          />

          <!-- 文本内容（无 meta 时回退） -->
          <template v-else>
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
          </template>

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

      <!-- 8.x 增量开发入口（应用完成时显示）：下次输入的新需求走增量流水线 -->
      <div v-if="canStartIncremental" class="flex justify-center pb-2">
        <button
          class="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-50 transition-colors"
          :disabled="isTransitioning"
          @click="handleStartIncremental"
        >
          <span v-if="incrementalDraft">✏️ 请输入新需求后发送...</span>
          <span v-else>🔄 增量开发</span>
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
