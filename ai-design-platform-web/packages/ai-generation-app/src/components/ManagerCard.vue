<!-- src/components/ManagerCard.vue — Manager 结构化消息卡片（按 card 类型内部分流渲染） -->
<script setup lang="ts">
import { computed, ref } from 'vue'
import type { ManagerCardMeta } from '@/types/generation'

const props = defineProps<{
  meta: ManagerCardMeta
  disabled?: boolean
}>()

const emit = defineEmits<{
  (e: 'option-click', option: string): void
}>()

const CARD_LABELS: Record<string, string> = {
  summary_card: '阶段总结',
  verdict_card: '把关裁决',
  diagnosis_card: '问题诊断',
  confirm_card: '确认请求',
  proposal_card: '方案建议',
  coverage_matrix: '覆盖矩阵',
  question_card: '提问',
  feedback_card: '反馈处置',
}

const cardLabel = computed(() => CARD_LABELS[props.meta.card] || 'Manager')

const cardStyle = computed(() => {
  switch (props.meta.card) {
    case 'verdict_card':
      return props.meta.data?.passed
        ? 'border-green-200 bg-green-50'
        : 'border-red-200 bg-red-50'
    case 'diagnosis_card':
      return 'border-amber-200 bg-amber-50'
    case 'confirm_card':
      return 'border-orange-200 bg-orange-50'
    case 'question_card':
      return 'border-blue-200 bg-blue-50'
    case 'coverage_matrix':
      return 'border-indigo-200 bg-indigo-50'
    case 'feedback_card':
      return 'border-yellow-200 bg-yellow-50'
    default:
      return 'border-gray-200 bg-white'
  }
})

// 10.2: 反馈处置卡 — 默认折叠的摘要行 (反馈摘要 + 处置动作 + 结果),
// 点击展开可见处置过程 (分类、重派任务、验证结果)。
const feedbackExpanded = ref(false)
const feedbackResultLabel = computed(() => {
  const result = props.meta.data?.result
  if (result === 'awaiting_confirm') return '待确认'
  if (result === 'rejected') return '已忽略'
  return result === 'dispatched' ? '已重派' : '处理中'
})

const verdictPassed = computed<boolean | null>(() =>
  props.meta.card === 'verdict_card' && props.meta.data
    ? props.meta.data.passed !== false
    : null,
)

const badgeClass = computed(() => {
  switch (props.meta.card) {
    case 'verdict_card':
      return verdictPassed.value ? 'bg-green-600 text-white' : 'bg-red-600 text-white'
    case 'diagnosis_card':
      return 'bg-amber-500 text-white'
    case 'question_card':
      return 'bg-blue-600 text-white'
    default:
      return 'bg-gray-700 text-white'
  }
})

const suggestion = computed(() => props.meta.data?.suggestion as string | undefined)
const matrix = computed(() => props.meta.data?.matrix as Record<string, any> | undefined)
</script>

<template>
  <div class="manager-card border rounded-lg px-3 py-2.5 text-sm" :class="cardStyle">
    <!-- 卡片头：类型标签 + 标题 -->
    <div class="flex items-center gap-2 mb-1">
      <span class="text-[10px] px-1.5 py-0.5 rounded-full font-medium shrink-0" :class="badgeClass">
        {{ cardLabel }}
      </span>
      <span v-if="meta.title" class="text-xs font-semibold text-gray-800">{{ meta.title }}</span>
    </div>

    <!-- 反馈处置（feedback_card，10.2）：折叠摘要行 + 展开处置过程 -->
    <div v-if="meta.card === 'feedback_card'" class="feedback-disposition">
      <div
        class="flex items-center gap-2 cursor-pointer hover:bg-yellow-100/50 rounded px-1 -mx-1 py-0.5"
        data-testid="feedback-card-toggle"
        @click="feedbackExpanded = !feedbackExpanded"
      >
        <span class="text-[10px] text-gray-400 shrink-0">{{ feedbackExpanded ? '▼' : '▶' }}</span>
        <span class="text-[10px] text-gray-400 shrink-0">💬</span>
        <span class="text-xs text-gray-700 truncate flex-1">
          反馈：{{ (meta.data?.feedback as string)?.slice(0, 40) }}{{ ((meta.data?.feedback as string)?.length || 0) > 40 ? '...' : '' }}
        </span>
        <span class="text-[10px] text-gray-500 shrink-0">
          {{ meta.data?.category_label || meta.data?.category || '' }} · {{ feedbackResultLabel }}
        </span>
      </div>
      <div v-if="feedbackExpanded" class="mt-1.5 pt-1.5 border-t border-yellow-100 text-xs text-gray-600 space-y-1">
        <div class="whitespace-pre-wrap break-words">"{{ meta.data?.feedback }}"</div>
        <div><span class="text-gray-400">分类：</span>{{ meta.data?.category_label || meta.data?.category || '未知' }}</div>
        <div v-if="meta.data?.reason"><span class="text-gray-400">依据：</span>{{ meta.data.reason }}</div>
        <div><span class="text-gray-400">处置动作：</span>{{ meta.data?.action || '—' }}</div>
        <div><span class="text-gray-400">结果：</span>{{ feedbackResultLabel }}</div>
        <!-- NOTE (spec drift, review): 后端在反馈消费点发射本卡, 验证结果由
             同流后续把关裁决卡 (verdict_card) 呈现 — spec 场景 "处置与重派
             执行完成 THEN 卡片" 的严格时序未实现, 见 dialog.py 注释。 -->
        <div class="text-[10px] text-gray-400">验证结果：见后续 Manager 把关裁决卡片</div>
      </div>
    </div>

    <!-- 把关裁决（verdict_card）：通过/未通过标识 -->
    <div
      v-else-if="meta.card === 'verdict_card' && verdictPassed !== null"
      class="mb-1 text-xs font-semibold"
      :class="verdictPassed ? 'text-green-700' : 'text-red-700'"
    >
      {{ verdictPassed ? '✓ 通过' : '✗ 未通过' }}
    </div>

    <!-- 正文 -->
    <div
      v-if="meta.card !== 'feedback_card' && meta.content"
      class="text-xs text-gray-700 whitespace-pre-wrap break-words"
    >
      {{ meta.content }}
    </div>

    <!-- 诊断建议（diagnosis_card） -->
    <div v-if="suggestion" class="mt-1.5 text-xs text-amber-800">
      <span class="font-medium">建议：</span>{{ suggestion }}
    </div>

    <!-- 覆盖矩阵（coverage_matrix） -->
    <div v-if="matrix" class="mt-1.5 text-xs text-gray-700">
      <div
        v-for="(v, k) in matrix"
        :key="k"
        class="flex justify-between gap-2 py-0.5 border-b border-gray-200 last:border-0"
      >
        <span class="text-gray-500">{{ k }}</span>
        <span class="font-mono">{{ typeof v === 'object' ? JSON.stringify(v) : v }}</span>
      </div>
    </div>

    <!-- 选项按钮 -->
    <div v-if="meta.options && meta.options.length" class="mt-2 space-y-1">
      <div class="text-[10px] text-gray-400 mb-1">点击选择：</div>
      <button
        v-for="opt in meta.options"
        :key="opt"
        class="block w-full text-left px-3 py-1.5 text-xs border border-blue-200 rounded-lg bg-blue-50 text-blue-700 hover:bg-blue-100 hover:border-blue-300 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        :disabled="disabled"
        @click="emit('option-click', opt)"
      >
        {{ opt }}
      </button>
    </div>
  </div>
</template>
