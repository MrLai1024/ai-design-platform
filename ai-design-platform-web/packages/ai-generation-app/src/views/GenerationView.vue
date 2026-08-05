<!-- src/views/GenerationView.vue -->
<script setup lang="ts">
import { onMounted, computed, ref, watch } from 'vue'
import { useGenerationStore } from '@/stores/generation'
import { useCodeParser } from '@/composables/useCodeParser'
import { useE2ERunner } from '@/composables/useE2ERunner'
import { useMultiAgent } from '@/composables/useMultiAgent'
import ChatPanel from '@/components/ChatPanel.vue'
import StepProgress from '@/components/StepProgress.vue'
import StageToolbar from '@/components/StageToolbar.vue'
import TabBar from '@/components/TabBar.vue'
import PreviewFrame from '@/components/PreviewFrame.vue'
import FileExplorer from '@/components/FileExplorer.vue'
import AnalysisStagePanel from '@/components/AnalysisStagePanel.vue'
import DesignStagePanel from '@/components/DesignStagePanel.vue'
import CodeStagePanel from '@/components/CodeStagePanel.vue'
import E2EStagePanel from '@/components/E2EStagePanel.vue'

const store = useGenerationStore()
useCodeParser()

const { submitE2EResults } = useMultiAgent()
// 由 E2EStagePanel 通过 PreviewFrame defineExpose + preview-iframe 事件注入
// 真实预览 iframe（I1）。模板表达式会解包 ref —— 写入必须经脚本函数。
const previewFrameRef = ref<HTMLIFrameElement | null>(null)
const { executeAll } = useE2ERunner(previewFrameRef)

function onPreviewIframe(iframe: HTMLIFrameElement | null): void {
  previewFrameRef.value = iframe
}

// Watch for e2e_start event to trigger E2E execution
watch(
  () => store.e2eTestCases,
  async (cases) => {
    if (cases.length > 0 && store.stage === 'e2e' && store.e2eUserConfirmed) {
      store.e2eRunning = true
      const allResults = await executeAll(cases, (result) => {
        store.addE2EResult(result)
      })
      store.e2eRunning = false
      await submitE2EResults(allResults)
    }
  },
)

const stepNodes = computed(() => store.currentStepNodes)

const currentStageTitle = computed(() => {
  const map: Record<string, string> = {
    analysis: '📋 需求规格文档',
    design: '📐 详细设计方案',
    code: '💻 功能开发',
    e2e: '🧪 E2E 验证',
  }
  return map[store.stage] || '阶段产出'
})

function handleNodeClick(node: (typeof stepNodes.value)[number]): void {
  store.setStage(node.key)
}

onMounted(() => {
  store.resetAll()
})
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

      <!-- StageToolbar（所有阶段共用，idle 和 done 时隐藏） -->
      <StageToolbar
        v-if="store.stage !== 'idle' && store.stage !== 'done'"
        :is-streaming="store.isStreaming"
      />

      <!-- 阶段容器切换 -->
      <AnalysisStagePanel v-if="store.stage === 'analysis'" />
      <DesignStagePanel v-else-if="store.stage === 'design'" />
      <CodeStagePanel v-else-if="store.stage === 'code'" />
      <E2EStagePanel
        v-else-if="store.stage === 'e2e'"
        @preview-iframe="onPreviewIframe"
      />

      <!-- 初始状态占位 -->
      <div
        v-if="store.stage === 'idle'"
        class="flex-1 flex items-center justify-center text-gray-400"
      >
        <div class="text-center">
          <p class="text-lg">输入需求，开始 AI 生成</p>
        </div>
      </div>

      <!-- 完成状态 -->
      <div
        v-if="store.stage === 'done'"
        class="flex-1 flex items-center justify-center text-gray-400"
      >
        <div class="text-center">
          <p class="text-lg text-green-600">✓ 所有阶段完成</p>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.e2e-container {
  overflow-y: auto;
}
</style>
