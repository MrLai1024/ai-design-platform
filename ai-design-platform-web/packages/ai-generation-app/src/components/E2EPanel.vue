<template>
  <div class="e2e-panel">
    <div class="e2e-header">
      <h3>E2E 测试</h3>
      <span class="e2e-summary">
        {{ passedCount }} / {{ totalCount }} 通过
      </span>
    </div>

    <div class="e2e-list">
      <div
        v-for="(testCase, index) in testCases"
        :key="testCase.id"
        class="e2e-case"
        :class="caseClass(testCase.id)"
      >
        <div class="e2e-case-header">
          <span class="e2e-case-icon">{{ caseIcon(testCase.id) }}</span>
          <span class="e2e-case-name">{{ testCase.name }}</span>
        </div>
        <p class="e2e-case-desc">{{ testCase.description }}</p>

        <div
          v-if="failedResult(testCase.id)"
          class="e2e-case-error"
        >
          <p>{{ failedResult(testCase.id)?.error }}</p>
          <img
            v-if="failedResult(testCase.id)?.screenshot"
            :src="failedResult(testCase.id)?.screenshot"
            class="e2e-screenshot"
            alt="失败截图"
          />
        </div>

        <div v-if="isCaseRunning(index)" class="e2e-case-running">
          执行中...
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { E2ETestCase, E2ECaseResult } from '../types/generation'

const props = defineProps<{
  testCases: E2ETestCase[]
  results: E2ECaseResult[]
  currentCaseIndex: number
  isRunning: boolean
}>()

const totalCount = computed(() => props.testCases.length)
const passedCount = computed(() => props.results.filter((r) => r.passed).length)

function caseResult(caseId: string): E2ECaseResult | undefined {
  return props.results.find((r) => r.caseId === caseId)
}

function failedResult(caseId: string): E2ECaseResult | undefined {
  const r = caseResult(caseId)
  return r && !r.passed ? r : undefined
}

function caseClass(caseId: string) {
  const r = caseResult(caseId)
  if (!r) return ''
  return r.passed ? 'case-passed' : 'case-failed'
}

function caseIcon(caseId: string): string {
  const r = caseResult(caseId)
  if (!r) return '⬜'
  return r.passed ? '✅' : '❌'
}

function isCaseRunning(index: number): boolean {
  return props.isRunning && props.currentCaseIndex === index
}
</script>

<style scoped>
.e2e-panel {
  padding: 16px;
  height: 100%;
  overflow-y: auto;
}
.e2e-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.e2e-header h3 {
  margin: 0;
  font-size: 16px;
}
.e2e-summary {
  font-size: 14px;
  color: var(--text-secondary);
}
.e2e-case {
  padding: 12px;
  border-radius: 8px;
  margin-bottom: 8px;
  border: 1px solid var(--border-color, #e5e7eb);
}
.case-passed {
  border-color: #22c55e;
  background: rgba(34, 197, 94, 0.05);
}
.case-failed {
  border-color: #ef4444;
  background: rgba(239, 68, 68, 0.05);
}
.e2e-case-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 500;
}
.e2e-case-desc {
  margin: 4px 0 0 0;
  font-size: 13px;
  color: var(--text-secondary, #6b7280);
}
.e2e-case-error {
  margin-top: 8px;
  padding: 8px;
  background: rgba(239, 68, 68, 0.05);
  border-radius: 4px;
  font-size: 12px;
}
.e2e-screenshot {
  max-width: 100%;
  margin-top: 8px;
  border: 1px solid var(--border-color, #e5e7eb);
  border-radius: 4px;
}
.e2e-case-running {
  margin-top: 8px;
  font-size: 12px;
  color: #3b82f6;
  animation: pulse 1.5s infinite;
}
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}
</style>
