// src/composables/useMultiAgent.ts
import { ref, readonly, type Ref } from 'vue'
import { useGenerationStore } from '@/stores/generation'
import { useStreamChat } from './useStreamChat'
import { useStagePrompts } from './useStagePrompts'
import type { ComponentLibrary } from '@/types/generation'

export function useMultiAgent() {
  const store = useGenerationStore()
  const { send, cancel: cancelStream, error: streamError } = useStreamChat()
  const { getAnalysisPrompt, getDesignPrompt, getCodeGenPrompt } = useStagePrompts()

  const isTransitioning = ref(false)

  // ── 阶段推进 ──

  /** 启动需求分析阶段 */
  async function startAnalysis(userContent: string, lib: ComponentLibrary): Promise<void> {
    store.setStage('analysis')
    store.setStageStatus('analysis', 'active')
    store.setRightPanelView('stage-output')

    await send({
      content: userContent,
      lib,
      messages: [
        { role: 'system', content: getAnalysisPrompt() },
        { role: 'user', content: userContent },
      ],
      stage: 'analysis',
    })
  }

  /** 需求分析阶段继续对话（用户回答 Agent 的提问） */
  async function continueAnalysis(userContent: string): Promise<void> {
    // 不传 messages — 让 send() 在添加完用户消息后从 store 构建完整消息列表
    // systemPrompt 确保后续轮次也使用需求分析角色
    await send({
      content: userContent,
      lib: store.currentLib,
      systemPrompt: getAnalysisPrompt(),
      stage: 'analysis',
    })
  }

  /** 用户确认需求分析，进入详细设计 */
  async function confirmAnalysis(): Promise<void> {
    const lastAssistant = store.lastAssistantMessage
    if (lastAssistant) {
      store.setStageOutput('analysis', lastAssistant.content)
    }
    store.completeCurrentStage()

    isTransitioning.value = true
    store.setStage('design')
    store.setStageStatus('design', 'active')
    store.setRightPanelView('stage-output')

    const spec = store.stageOutputs.analysis || ''
    await send({
      lib: store.currentLib,
      messages: [
        { role: 'system', content: getDesignPrompt() },
        { role: 'user', content: `请基于以下需求规格文档输出详细设计方案：\n\n${spec}` },
      ],
      stage: 'design',
    })
    isTransitioning.value = false
  }

  /** 用户确认详细设计，进入代码实现 */
  async function confirmDesign(): Promise<void> {
    const lastAssistant = store.lastAssistantMessage
    if (lastAssistant) {
      store.setStageOutput('design', lastAssistant.content)
    }
    store.completeCurrentStage()

    isTransitioning.value = true
    store.enterCodeStage()

    const spec = store.stageOutputs.analysis || ''
    const design = store.stageOutputs.design || ''
    await send({
      lib: store.currentLib,
      messages: [
        { role: 'system', content: getCodeGenPrompt(store.currentLib) },
        { role: 'user', content: `需求规格：\n${spec}\n\n设计方案：\n${design}\n\n请生成完整代码。` },
      ],
      stage: 'code',
    })
    isTransitioning.value = false
  }

  /** 取消当前请求 */
  function cancel(): void {
    cancelStream()
  }

  /** 判断当前阶段是否完成（最后一条 assistant 消息流式结束） */
  function isCurrentStageFinished(): boolean {
    if (store.isStreaming) return false
    const last = store.lastAssistantMessage
    if (!last || last.isStreaming) return false
    // 有文本内容或有思考内容都视为阶段完成
    return last.content.length > 0 || (last.reasoningContent?.length ?? 0) > 0
  }

  /** 点击已完成节点，查看产出 */
  function viewStageOutput(stageKey: 'analysis' | 'design'): void {
    store.setStage(stageKey)
    store.setRightPanelView('stage-output')
  }

  /** 返回当前活跃阶段的视图 */
  function backToCurrentStage(): void {
    // Find the active stage from stageStatus
    const statuses = store.stageStatus
    for (const key of ['analysis', 'design', 'code'] as const) {
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
    // Fallback: if no active stage, go to the stage with done status
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

  return {
    startAnalysis,
    continueAnalysis,
    confirmAnalysis,
    confirmDesign,
    cancel,
    isTransitioning: readonly(isTransitioning) as Ref<boolean>,
    streamError,
    isCurrentStageFinished,
    viewStageOutput,
    backToCurrentStage,
  }
}
