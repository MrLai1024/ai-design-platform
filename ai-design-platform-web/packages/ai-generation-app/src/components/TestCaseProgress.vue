<!-- src/components/TestCaseProgress.vue
  用例执行进度：DSL 用例（scenario 为标题，兼容旧 name）；requires_browser
  跳过结果显示 ⏭（6.7）。 -->
<script setup lang="ts">
import { computed } from 'vue'
import { useGenerationStore } from '@/stores/generation'

const store = useGenerationStore()

const totalCases = computed(() => store.e2eTestCases.length)
const executedCases = computed(() => store.e2eResults.length)
const passedCases = computed(() => store.e2eResults.filter(r => r.passed).length)
const progress = computed(() => totalCases.value > 0 ? Math.round((executedCases.value / totalCases.value) * 100) : 0)

function caseLabel(tc: { scenario?: string; name?: string }): string {
  return tc.scenario || tc.name || ''
}

function resultIcon(result?: { status?: string; passed?: boolean }): string {
  if (!result) return '⏸'
  if (result.status === 'skipped_requires_browser') return '⏭'
  return result.passed ? '✅' : '❌'
}

function resultClass(result?: { status?: string; passed?: boolean }): Record<string, boolean> {
  if (!result) return {}
  if (result.status === 'skipped_requires_browser') return { 'bg-amber-50': true }
  return result.passed ? { 'bg-green-50': true } : { 'bg-red-50': true }
}
</script>

<template>
  <div class="p-3">
    <div class="text-sm font-medium text-gray-700 mb-2">
      🧪 E2E 测试执行
      <span class="text-xs text-gray-400 ml-2">
        {{ executedCases }}/{{ totalCases }} 已完成
      </span>
    </div>

    <div class="w-full bg-gray-200 rounded-full h-2 mb-3">
      <div
        class="h-2 rounded-full transition-all duration-300"
        :class="store.e2eRunning ? 'bg-blue-500' : 'bg-green-500'"
        :style="{ width: progress + '%' }"
      />
    </div>

    <div class="space-y-1">
      <div
        v-for="(tc, idx) in store.e2eTestCases"
        :key="tc.id"
        class="flex items-center gap-2 px-3 py-1.5 text-sm rounded"
        :class="{
          'bg-blue-50': store.e2eCurrentCaseId === tc.id && store.e2eRunning,
          ...resultClass(store.e2eResults[idx]),
        }"
      >
        <span v-if="store.e2eCurrentCaseId === tc.id && store.e2eRunning" class="text-blue-500 animate-spin">⏳</span>
        <span v-else>{{ resultIcon(store.e2eResults[idx]) }}</span>
        <span>{{ caseLabel(tc) }}</span>
        <span v-if="store.e2eResults[idx]?.error" class="text-red-500 text-xs ml-auto truncate max-w-[200px]">
          {{ store.e2eResults[idx].error }}
        </span>
      </div>
    </div>

    <div v-if="!store.e2eRunning && executedCases > 0" class="mt-2 text-sm text-center">
      <span class="text-green-600">{{ passedCases }} 通过</span>
      <span v-if="executedCases - passedCases > 0" class="text-red-600 ml-2">
        {{ executedCases - passedCases }} 失败/跳过
      </span>
    </div>
  </div>
</template>
