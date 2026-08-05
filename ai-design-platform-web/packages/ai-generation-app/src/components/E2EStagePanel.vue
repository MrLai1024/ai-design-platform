<!-- src/components/E2EStagePanel.vue
  Phase 1: Test Designer 产出的 DSL 用例清单（覆盖矩阵卡片走 ChatPanel 的
  manager_message）+ rendered MD 摘要；确认后进入执行。
  Phase 2: 用例执行进度 + PreviewFrame；requires_browser 人工执行清单（6.7）；
  Test Diagnoser 三方分类结果（6.4）。
  事件 'preview-iframe' (review I1): PreviewFrame defineExpose({ iframe }) →
  组件 ref watcher → emit 给 GenerationView 写入 useE2ERunner 的
  previewFrameRef（模板中不能直接传 Ref prop —— 会被自动解包）。 -->
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useGenerationStore } from '@/stores/generation'
import { useMultiAgent } from '@/composables/useMultiAgent'
import StreamDocument from './StreamDocument.vue'
import PreviewFrame from './PreviewFrame.vue'
import TestCaseProgress from './TestCaseProgress.vue'

const emit = defineEmits<{
  'preview-iframe': [iframe: HTMLIFrameElement | null]
}>()

const store = useGenerationStore()
const { confirmStage, isTransitioning } = useMultiAgent()

// 组件 ref → PreviewFrame defineExpose({ iframe }) → emit 给外部 runner ref
const previewFrameComp = ref<{ iframe: HTMLIFrameElement | null } | null>(null)
watch(previewFrameComp, (comp) => {
  emit('preview-iframe', comp?.iframe ?? null)
})

const manualCases = computed(() =>
  store.e2eTestCases.filter((tc) => tc.requires_browser),
)
const diagnosis = computed(() => store.e2eDiagnosis)

function caseLabel(tc: { id: string; scenario?: string; name?: string }): string {
  return tc.scenario || tc.name || tc.id
}

async function handleConfirmCases(): Promise<void> {
  // 防重复点击：isTransitioning 期间禁用按钮（review I3）
  if (isTransitioning.value) return
  store.confirmE2ECases()
  await confirmStage('e2e')
}
</script>

<template>
  <div class="flex-1 flex flex-col overflow-auto">
    <!-- Phase 1: Test Designer 用例清单审查 -->
    <template v-if="!store.e2eUserConfirmed">
      <!-- DSL 用例清单（6.1 规范产物） -->
      <div v-if="store.e2eTestCases.length" class="p-3 border-b border-gray-200">
        <div class="text-sm font-medium text-gray-700 mb-2">
          🧩 测试用例清单（{{ store.e2eTestCases.length }} 条 DSL 用例）
        </div>
        <div class="space-y-2">
          <div
            v-for="tc in store.e2eTestCases"
            :key="tc.id"
            class="rounded border border-gray-200 p-2 text-xs"
          >
            <div class="flex items-center gap-2">
              <span class="font-mono font-medium text-gray-800">{{ tc.id }}</span>
              <span class="text-gray-500">[{{ tc.requirement_id }}]</span>
              <span class="text-gray-700">{{ tc.scenario }}</span>
              <span
                v-if="tc.requires_browser"
                class="ml-auto px-1.5 py-0.5 rounded bg-amber-100 text-amber-700"
                title="多页面流转/登录态等复杂用例：一期跳过，列入人工执行清单"
              >requires_browser</span>
            </div>
            <div class="mt-1 text-gray-500">
              <span
                v-for="(step, i) in tc.steps.slice(0, 4)"
                :key="i"
                class="mr-2"
              >
                {{ step.action }}
                <span class="font-mono">{{ step.target.by }}:{{ step.target.value }}</span>
              </span>
              <span v-if="tc.steps.length > 4" class="text-gray-400">…</span>
            </div>
          </div>
        </div>
        <!-- requires_browser 人工执行清单（6.7） -->
        <div v-if="manualCases.length" class="mt-2 text-xs text-amber-700">
          ⚠️ 以下 {{ manualCases.length }} 条复杂用例一期跳过，列入人工执行清单：
          <span v-for="(tc, i) in manualCases" :key="tc.id">
            {{ i > 0 ? '、' : '' }}{{ caseLabel(tc) }}（{{ tc.id }}）
          </span>
        </div>
      </div>

      <!-- rendered MD 摘要（后端 e2e_test_cases_md） -->
      <StreamDocument
        :content="store.e2eTestCasesMd || store.docStreamingContent"
        :is-streaming="store.docIsStreaming || store.isStreaming"
        language="md"
      />
      <div
        v-if="!store.isStreaming && (store.e2eTestCasesMd || store.e2eTestCases.length)"
        class="flex justify-center p-3 border-t border-gray-200"
      >
        <button
          class="px-4 py-2 bg-green-600 text-white rounded-lg text-sm font-medium hover:bg-green-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          :disabled="isTransitioning"
          @click="handleConfirmCases"
        >
          {{ isTransitioning ? '确认中...' : '✓ 确认测试用例，开始执行测试' }}
        </button>
      </div>
    </template>

    <!-- Phase 2: Split-screen test execution -->
    <template v-else>
      <div class="flex flex-col h-full" style="height: calc(100vh - 200px);">
        <div class="h-[45%] overflow-auto border-b border-gray-200">
          <TestCaseProgress />
          <!-- requires_browser 人工执行清单（6.7） -->
          <div v-if="manualCases.length" class="px-3 pb-2 text-xs text-amber-700">
            ⚠️ 人工执行清单（requires_browser，一期跳过）：
            <span v-for="(tc, i) in manualCases" :key="tc.id">
              {{ i > 0 ? '、' : '' }}{{ caseLabel(tc) }}（{{ tc.id }}）
            </span>
          </div>
          <!-- Test Diagnoser 三方分类（6.4） -->
          <div
            v-if="diagnosis && diagnosis.counts"
            class="px-3 pb-2 text-xs"
            :class="diagnosis.rollback_case_ids.length ? 'text-red-600' : 'text-gray-600'"
          >
            <div class="font-medium mb-1">
              🔬 Test Diagnoser 分类：预期失效 {{ diagnosis.counts.expected_broken }} ·
              选择器耦合 {{ diagnosis.counts.selector_coupled }} ·
              真实回归 {{ diagnosis.counts.real_regression }}
            </div>
            <div
              v-for="d in diagnosis.diagnoses"
              :key="d.case_id"
              class="pl-2 border-l-2 border-gray-300"
            >
              <span class="font-mono">{{ d.case_id }}</span> → {{ d.classification }}：{{ d.reason }}
            </div>
          </div>
        </div>
        <div class="flex-1 relative">
          <PreviewFrame ref="previewFrameComp" />
        </div>
      </div>
    </template>
  </div>
</template>
