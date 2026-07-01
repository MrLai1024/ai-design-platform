// src/composables/useMultiAgent.ts
import { ref } from 'vue'
import { useGenerationStore } from '../stores/generation'
import { useStreamChat } from './useStreamChat'
import type { Stage, ComponentLibrary, E2ECaseResult } from '../types/generation'

export function useMultiAgent() {
  const store = useGenerationStore()
  const { send, cancel: cancelStream } = useStreamChat()

  const isTransitioning = ref(false)
  const streamError = ref<string | null>(null)

  async function startGeneration(content: string, lib: ComponentLibrary) {
    store.resetAll()
    store.setCurrentLib(lib)
    store.setStage('analysis')
    store.setStageStatus('analysis', 'active')
    store.setRightPanelView('stage-output')

    isTransitioning.value = true
    try {
      await send({
        content,
        lib,
        stage: 'analysis',
      })
    } catch (e: any) {
      streamError.value = e.message || 'Generation failed'
    } finally {
      isTransitioning.value = false
    }
  }

  async function confirmStage(stage: Stage) {
    isTransitioning.value = true
    try {
      const response = await fetch('/api/v1/generation/confirm', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          generation_id: store.currentGenerationId,
          stage,
        }),
      })
      if (!response.ok) throw new Error('Confirmation failed')
    } catch (e: any) {
      streamError.value = e.message
    } finally {
      isTransitioning.value = false
    }
  }

  async function submitE2EResults(results: E2ECaseResult[]) {
    isTransitioning.value = true
    try {
      for (const result of results) {
        await fetch('/api/v1/e2e/result', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            generation_id: store.currentGenerationId,
            case_id: result.caseId,
            passed: result.passed,
            error: result.error,
            screenshot: result.screenshot,
          }),
        })
      }
    } catch (e: any) {
      streamError.value = e.message
    } finally {
      isTransitioning.value = false
    }
  }

  function cancel() {
    cancelStream()
  }

  return {
    isTransitioning,
    streamError,
    startGeneration,
    confirmStage,
    submitE2EResults,
    cancel,
  }
}
