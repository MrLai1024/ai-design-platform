// src/composables/useMultiAgent.ts
import { ref } from 'vue'
import { useGenerationStore } from '../stores/generation'
import { useStreamChat } from './useStreamChat'
import { handleCodeSSEEvent } from './useCodeStream'
import type { Stage, E2ECaseResult } from '../types/generation'

export function useMultiAgent() {
  const store = useGenerationStore()
  const { send, cancel: cancelStream } = useStreamChat()

  const isTransitioning = ref(false)
  const streamError = ref<string | null>(null)
  let currentAbortController: AbortController | null = null

  function getAbortController(): AbortController {
    if (currentAbortController) {
      try { currentAbortController.abort() } catch { /* ignore */ }
    }
    currentAbortController = new AbortController()
    return currentAbortController
  }

  async function sendFeedback(feedback: string): Promise<void> {
    if (!store.currentGenerationId) return
    try {
      await fetch('/api/v1/generation/feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          generation_id: store.currentGenerationId,
          stage: store.stage,
          feedback,
        }),
      })
      // After feedback is received, restart the graph stream to pick up changes
      await confirmStage(store.stage)
    } catch (e: any) {
      streamError.value = e.message || 'Feedback failed'
    }
  }

  function cancelGeneration(): void {
    if (currentAbortController) {
      try { currentAbortController.abort() } catch { /* ignore */ }
      currentAbortController = null
    }
    store.setStreaming(false)
    isTransitioning.value = false
  }

  async function startGeneration(content: string, systemPrompt?: string) {
    store.resetAll()
    store.setStage('analysis')
    store.setStageStatus('analysis', 'active')
    store.setRightPanelView('stage-output')

    isTransitioning.value = true
    try {
      await send({
        content,
        stage: 'analysis',
        systemPrompt,
      })
    } catch (e: any) {
      streamError.value = e.message || 'Generation failed'
    } finally {
      isTransitioning.value = false
    }
  }

  /** 启动 graph 流水线 — /api/v1/generation/stream (PRD 在 graph 内流式生成) */
  async function startGraphGeneration(content: string) {
    store.setStage('analysis')
    store.setStageStatus('analysis', 'active')
    store.setStagePhase('generating')
    store.docIsStreaming = true
    store.docStreamingContent = ''
    store.isStreaming = true

    const chatMessages = store.messages
      .filter((m) => !m.isStreaming)
      .map((m) => ({ role: m.role, content: m.content }))

    isTransitioning.value = true
    try {
      const response = await fetch('/api/v1/generation/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          messages: chatMessages,
          model: 'deepseek-v4-pro',
        }),
      })

      if (!response.ok) {
        const errText = await response.text()
        throw new Error(`Graph error: ${response.status} ${errText}`)
      }

      const reader = response.body!.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const frames = buffer.split('\n\n')
        buffer = frames.pop() || ''
        for (const frame of frames) {
          if (!frame.trim()) continue
          const dataLine = frame.split('\n').find((l) => l.startsWith('data:'))
          if (!dataLine) continue
          const raw = dataLine.slice(5).trimStart()
          if (!raw || raw === '[DONE]') continue
          try {
            const event = JSON.parse(raw)
            dispatchGraphEvent(event._t, event)
          } catch { /* skip */ }
        }
      }
    } catch (e: any) {
      streamError.value = e.message || 'Graph generation failed'
    } finally {
      store.isStreaming = false
      store.docIsStreaming = false
      isTransitioning.value = false
    }
  }

  /** 分发 Graph SSE 事件到 store */
  function dispatchGraphEvent(eventType: string, event: any): void {
    switch (eventType) {
      case 'meta':
        if (event.generation_id) store.setGenerationId(event.generation_id)
        break
      case 'stage_start':
        store.setStageStatus(event.stage, 'active')
        store.setStage(event.stage as Stage)
        if (event.phase) store.setStagePhase(event.phase)
        if (event.stage === 'code') {
          store.setCodeViewTab('files')
        }
        break
      case 'stage_complete':
        store.setStageStatus(event.stage, 'done')
        store.setStagePhase('complete')
        if (event.summary) store.setStageOutput(event.stage as Stage, event.summary)
        break
      case 'human_confirm_required':
        store.setAwaitingConfirm(true)
        break
      case 'prd_reasoning':
        store.appendPRDReasoning(event.text || '')
        break
      case 'prd_generate_start':
        store.resetDocContent()
        break
      case 'prd_section':
        store.appendPRDContent(event.content || '')
        store.appendDocContent(event.content || '')
        break
      case 'prd_generate_done':
        store.finishPRDReasoning()
        store.setDocComplete(event.full_content || '')
        if (event.full_content) store.setStageOutput('analysis', event.full_content)
        break
      case 'doc_chunk':
        store.appendDocContent(event.content || '')
        break
      case 'design_gen_start':
        store.prdReasoningContent = ''
        store.prdReasoningDurationMs = 0
        store.resetDocContent()
        break
      case 'design_gen_done':
        store.finishPRDReasoning()
        store.setDocComplete(event.full_content || '')
        if (event.full_content) store.setStageOutput('design', event.full_content)
        break
      case 'code_gen_start':
        store.initFileTree(event.files || [])
        handleCodeSSEEvent(event)
        break
      case 'file_start':
        store.setCurrentGeneratingFile(event.path)
        handleCodeSSEEvent(event)
        break
      case 'file_chunk':
        store.appendFileContent(event.path, event.content || '')
        handleCodeSSEEvent(event)
        break
      case 'file_complete':
        store.finalizeFile(event.path)
        handleCodeSSEEvent(event)
        break
      case 'tool_call':
        store.addToolTrace({ type: 'call', tool: event.tool, args: event.args, status: 'running' })
        handleCodeSSEEvent(event)
        break
      case 'tool_result':
        // Match to last running trace of same tool
        for (let i = store.toolTraces.length - 1; i >= 0; i--) {
          if (store.toolTraces[i]!.tool === event.tool && store.toolTraces[i]!.status === 'running') {
            store.updateToolTrace(store.toolTraces[i]!.id, {
              type: 'result', status: event.ok ? 'done' : 'error',
              summary: event.summary || (event.ok ? 'Done' : 'Error'),
            })
            break
          }
        }
        handleCodeSSEEvent(event)
        break
      case 'code_gen_done':
      case 'thinking_chunk':
      case 'compile_status':
        handleCodeSSEEvent(event)
        break
        break
      case 'review_agents_start':
        store.initReviewAgents(event.agents || [])
        break
      case 'review_agent_chunk':
        store.setAgentRunning(event.agent)
        store.appendAgentFinding(event.agent, {
          severity: event.issue?.severity || 'medium',
          file: event.issue?.file || '',
          line: event.issue?.line || 0,
          title: event.issue?.title || '',
          description: event.issue?.description || '',
          fix: event.issue?.fix || '',
        })
        break
      case 'review_agent_done':
        store.setAgentDone(event.agent)
        break
      case 'review_report_ready':
        store.reviewReportHtml = event.report_html
        store.docStreamingContent = event.report_html || ''
        break
      case 'e2e_cases_gen_start':
        store.resetDocContent()
        break
      case 'e2e_cases_gen_done':
        store.setE2ECasesDoc(event.full_content || '')
        store.setDocComplete(event.full_content || '')
        break
      case 'e2e_execute_start':
        store.setE2ETestCases(event.test_cases || [])
        store.clearE2EResults()
        break
      case 'e2e_case_start':
        store.setCurrentE2ECase(event.case_id)
        break
      case 'e2e_case_result':
        store.addE2EResult({
          caseId: event.case_id, passed: event.passed,
          error: event.error, screenshot: event.screenshot,
        })
        break
      case 'e2e_complete':
        store.setStageStatus('e2e', event.passed ? 'done' : 'pending')
        store.e2eRunning = false
        break
      case 'e2e_execute_done':
        store.setE2EComplete({ total: event.total || 0, passed: event.passed || 0, failed: event.failed || 0 })
        break
      case 'graph_complete':
        store.setStage('done')
        break
      case 'stage_rollback':
        store.addRollbackEvent({ from: event.from, to: event.to, reason: event.reason, failedCases: event.failed_cases })
        store.setStage(event.to as Stage)
        store.setStageStatus(event.to, 'active')
        break
      case 'loop_warning':
        console.warn(`Loop warning: ${event.reason}`)
        break
      case 'loop_break':
        store.setNeedsManualReview(true)
        store.setLoopBreakReason(event.reason)
        break
      case 'complete':
      case 'done':
        break
      case 'error':
        streamError.value = event.message || 'Unknown error'
        break
    }
  }

  async function confirmStage(stage: Stage) {
    isTransitioning.value = true
    store.setAwaitingConfirm(false)

    // First transitions: PRD done (analysis) or design done (design)
    // Graph hasn't started yet, so send pre-filled state
    const needsFreshStart = stage === 'analysis' || stage === 'design' || stage === 'code'
    const body: Record<string, any> = {
      model: 'deepseek-v4-pro',

      mode: 'graph',
    }

    if (needsFreshStart) {
      // Pre-fill completed stages
      const prefillMessages: Array<{role: string; content: string}> = []
      prefillMessages.push({ role: 'user', content: store.stageOutputs.analysis || store.docStreamingContent })
      if (store.stageOutputs.design) {
        prefillMessages.push({ role: 'assistant', content: store.stageOutputs.design })
      }
      if (store.stageOutputs.code) {
        prefillMessages.push({ role: 'assistant', content: store.stageOutputs.code })
      }
      body.messages = prefillMessages
      body.skip_analysis = true
      // Carry the generation_id across fresh-start confirms — otherwise the
      // gateway generates a NEW id per request and backend state (incl. the
      // background architecture-spec task) is unreachable on the next phase.
      if (store.currentGenerationId) {
        body.generation_id = store.currentGenerationId
      }
    } else {
      // Resume graph for code+
      body.messages = []
      body.generation_id = store.currentGenerationId
      body.mode = 'resume'
    }

    try {
      const controller = getAbortController()
      const response = await fetch('/api/v1/generation/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal: controller.signal,
      })
      if (!response.ok) throw new Error(`Confirm failed: ${response.status}`)

      const reader = response.body!.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const frames = buffer.split('\n\n')
        buffer = frames.pop() || ''
        for (const frame of frames) {
          if (!frame.trim()) continue
          const dataLine = frame.split('\n').find((l) => l.startsWith('data:'))
          if (!dataLine) continue
          const raw = dataLine.slice(5).trimStart()
          if (!raw || raw === '[DONE]') continue
          try {
            const event = JSON.parse(raw)
            dispatchGraphEvent(event._t, event)
          } catch { /* skip */ }
        }
      }
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
    startGraphGeneration,
    confirmStage,
    submitE2EResults,
    sendFeedback,
    cancelGeneration,
    cancel,
  }
}
