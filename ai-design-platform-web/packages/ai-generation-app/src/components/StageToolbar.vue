<!-- src/components/StageToolbar.vue -->
<script setup lang="ts">
import { computed } from 'vue'
import { useGenerationStore } from '@/stores/generation'
import { useMultiAgent } from '@/composables/useMultiAgent'

const props = withDefaults(defineProps<{
  title?: string
  showNextButton?: boolean
  nextLabel?: string
  isStreaming?: boolean
}>(), {
  title: '',
  showNextButton: false,
  nextLabel: '下一步 ▸',
  isStreaming: false,
})

const emit = defineEmits<{
  next: []
}>()

const store = useGenerationStore()
const { confirmStage } = useMultiAgent()

const stageTitle = computed(() => {
  if (props.title) return props.title
  const map: Record<string, string> = {
    analysis: '📋 需求规格文档',
    design: '📐 详细设计方案',
    code: '💻 功能开发',
    e2e: '🧪 E2E 验证',
  }
  return map[store.stage] || '阶段产出'
})

async function handleNext(): Promise<void> {
  if (store.isStreaming) return
  emit('next')
  await confirmStage(store.stage)
}
</script>

<template>
  <div class="flex items-center justify-between px-4 py-2 bg-white border-b border-gray-200">
    <div class="flex items-center gap-2">
      <span class="text-sm font-medium text-gray-700">{{ stageTitle }}</span>
      <!-- 只在 graph 生成阶段显示"生成中"，Q&A 的 isStreaming 不算 -->
      <span
        v-if="store.stagePhase === 'generating' && store.isStreaming"
        class="text-xs text-blue-500 animate-pulse"
      >
        ▊ 生成中...
      </span>
      <span
        v-else-if="showNextButton || store.showNextButton"
        class="text-xs text-green-600"
      >
        ✓ 生成完成
      </span>
      <span
        v-else-if="store.stage === 'analysis' && store.stagePhase !== 'generating'"
        class="text-xs text-gray-400"
      >
        等待反问完成...
      </span>
    </div>

    <div class="flex items-center gap-2">
      <slot name="extra-actions" />
      <button
        v-if="showNextButton || store.showNextButton"
        class="px-3 py-1 bg-blue-600 text-white text-xs rounded hover:bg-blue-700 disabled:opacity-50 transition-colors"
        :disabled="store.isStreaming"
        @click="handleNext"
      >
        {{ nextLabel }}
      </button>
    </div>
  </div>
</template>
