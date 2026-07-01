<!-- src/views/GenerationView.vue -->
<script setup lang="ts">
import { onMounted, computed, ref, watch } from 'vue'
import { useGenerationStore } from '@/stores/generation'
import { useCodeParser } from '@/composables/useCodeParser'
import { useE2ERunner } from '@/composables/useE2ERunner'
import { useMultiAgent } from '@/composables/useMultiAgent'
import ChatPanel from '@/components/ChatPanel.vue'
import StepProgress from '@/components/StepProgress.vue'
import StageOutput from '@/components/StageOutput.vue'
import TabBar from '@/components/TabBar.vue'
import PreviewFrame from '@/components/PreviewFrame.vue'
import FileExplorer from '@/components/FileExplorer.vue'
import E2EPanel from '@/components/E2EPanel.vue'

const store = useGenerationStore()
useCodeParser()

const { submitE2EResults } = useMultiAgent()
const previewFrameRef = ref<HTMLIFrameElement | null>(null)
const { currentCaseIndex, executeAll } = useE2ERunner(previewFrameRef)

const e2eCurrentIndex = computed(() => currentCaseIndex.value)

// Watch for e2e_start event to trigger E2E execution
watch(
  () => store.e2eTestCases,
  async (cases) => {
    if (cases.length > 0 && store.stage === 'e2e') {
      store.e2eRunning = true
      const allResults = await executeAll(cases, (result) => {
        store.addE2EResult(result)
      })
      store.e2eRunning = false
      await submitE2EResults(allResults)
    }
  },
)

function viewStageOutput(stageKey: 'analysis' | 'design'): void {
  store.setStage(stageKey)
  store.setRightPanelView('stage-output')
}

function backToCurrentStage(): void {
  const statuses = store.stageStatus
  for (const key of ['analysis', 'design', 'code', 'review', 'e2e'] as const) {
    if (statuses[key] === 'active') {
      store.setStage(key)
      if (key === 'code') {
        store.setRightPanelView(store.codeViewTab)
      } else {
        store.setRightPanelView('stage-output')
      }
      return
    }
  }
  if (statuses['code'] === 'done') {
    store.setStage('code')
    store.setRightPanelView(store.codeViewTab)
  } else if (statuses['design'] === 'done') {
    store.setStage('design')
    store.setRightPanelView('stage-output')
  } else if (statuses['analysis'] === 'done') {
    store.setStage('analysis')
    store.setRightPanelView('stage-output')
  }
}

onMounted(() => {
  store.resetAll()
})

const stepNodes = computed(() => store.currentStepNodes)

const currentStageTitle = computed(() => {
  const map: Record<string, string> = {
    analysis: '需求规格文档',
    design: '详细设计方案',
  }
  return map[store.stage] || '阶段产出'
})

const currentStageContent = computed(() => {
  if (store.stage === 'analysis') return store.stageOutputs.analysis
  if (store.stage === 'design') return store.stageOutputs.design
  return store.stageOutputs[store.stage as 'analysis' | 'design'] || null
})

const codeTabs = [
  { key: 'preview' as const, label: '实时预览' },
  { key: 'files' as const, label: '工程文件' },
]

function handleNodeClick(node: (typeof stepNodes.value)[number]): void {
  if (node.key === 'analysis' || node.key === 'design') {
    viewStageOutput(node.key)
  }
}

function handleStageOutputSave(content: string): void {
  const key = store.stage as 'analysis' | 'design'
  store.setStageOutput(key, content)
}
</script>

<template>
  <div class="generation-view flex h-[calc(100vh-80px)]">
    <!-- 左侧：聊天面板 -->
    <div class="w-[30%] min-w-[320px] border-r border-gray-200">
      <ChatPanel />
    </div>

    <!-- 右侧：步骤条 + 内容区 -->
    <div class="flex-1 min-w-[400px] flex flex-col">
      <StepProgress
        :nodes="stepNodes"
        :current-stage="store.stage"
        @node-click="handleNodeClick"
      />

      <!-- 需求分析/详细设计阶段：展示 StageOutput -->
      <div
        v-if="(store.stage === 'analysis' || store.stage === 'design') && store.rightPanelView === 'stage-output'"
        class="flex-1 flex flex-col"
      >
        <!-- 返回按钮（当查看已完成阶段产出时显示） -->
        <div
          v-if="store.stageStatus[store.stage] === 'done'"
          class="px-4 py-1.5 bg-gray-50 border-b border-gray-200"
        >
          <button
            class="text-xs text-blue-600 hover:text-blue-800"
            @click="backToCurrentStage()"
          >
            ← 返回当前阶段
          </button>
        </div>
        <StageOutput
          class="flex-1"
          :title="currentStageTitle"
          :content="currentStageContent"
          @save="handleStageOutputSave"
        />
      </div>

      <!-- 代码实现阶段：TabBar + 预览/文件 -->
      <template v-if="store.stage === 'code' && store.rightPanelView !== 'stage-output'">
        <TabBar
          :tabs="codeTabs"
          :active-tab="store.codeViewTab"
          @select="store.setCodeViewTab($event)"
        />

        <div class="flex-1 relative">
          <div v-show="store.codeViewTab === 'preview'" class="absolute inset-0">
            <PreviewFrame />
          </div>
          <div v-show="store.codeViewTab === 'files'" class="absolute inset-0">
            <FileExplorer />
          </div>
        </div>
      </template>

      <!-- E2E Stage: show test panel -->
      <div v-if="store.stage === 'e2e'" class="flex-1 e2e-container">
        <E2EPanel
          :test-cases="store.e2eTestCases"
          :results="store.e2eResults"
          :current-case-index="e2eCurrentIndex"
          :is-running="store.e2eRunning"
        />
      </div>

      <!-- Manual review banner -->
      <div v-if="store.needsManualReview" class="manual-review-banner">
        自动流程已熔断，请人工复核
        <span v-if="store.loopBreakReason">原因：{{ store.loopBreakReason }}</span>
      </div>

      <!-- 初始状态占位 -->
      <div
        v-if="store.stage === 'idle'"
        class="flex-1 flex items-center justify-center text-gray-400"
      >
        <div class="text-center">
          <p class="text-lg">输入需求，开始 AI 生成</p>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.manual-review-banner {
  margin: 0 16px 8px;
  padding: 10px 14px;
  background: #fef3c7;
  border: 1px solid #f59e0b;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 500;
  color: #92400e;
}

.manual-review-banner span {
  display: block;
  margin-top: 4px;
  font-size: 12px;
  font-weight: 400;
  color: #a16207;
}

.e2e-container {
  overflow-y: auto;
}
</style>
