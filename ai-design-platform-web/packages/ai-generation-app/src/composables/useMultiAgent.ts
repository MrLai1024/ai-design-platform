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

  async function startGeneration(content: string, lib: ComponentLibrary, systemPrompt?: string) {
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
        systemPrompt,
      })
    } catch (e: any) {
      streamError.value = e.message || 'Generation failed'
    } finally {
      isTransitioning.value = false
    }
  }

  /** 启动 PRD 文档流式生成 — 调用 /api/v1/prd/stream */
  async function startGraphGeneration(content: string, lib: ComponentLibrary) {
    store.setStage('analysis')
    store.setStageStatus('analysis', 'active')
    store.setStagePhase('generating')
    store.setCurrentLib(lib)
    store.docIsStreaming = true
    store.docStreamingContent = ''
    store.isStreaming = true

    const chatMessages = store.messages
      .filter((m) => !m.isStreaming)
      .map((m) => ({ role: m.role, content: m.content }))

    isTransitioning.value = true
    try {
      console.log('[PRD] Sending', chatMessages.length, 'messages to /api/v1/prd/stream')
      const response = await fetch('/api/v1/prd/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages: chatMessages, model: 'glm-5.2' }),
      })

      if (!response.ok) {
        const errText = await response.text()
        throw new Error(`PRD API error: ${response.status} ${errText}`)
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
            if (event._t === 'doc_chunk') {
              store.appendDocContent(event.content || '')
            } else if (event._t === 'reasoning') {
              store.appendPRDReasoning(event.text || '')
            } else if (event._t === 'prd_complete') {
              store.finishPRDReasoning()
              store.setDocComplete(store.docStreamingContent)
              store.setStageOutput('analysis', store.docStreamingContent)
              store.setStagePhase('complete')
              store.setAwaitingConfirm(true)
            } else if (event._t === 'error') {
              streamError.value = event.message || 'PRD generation error'
            }
          } catch { /* skip */ }
        }
      }
    } catch (e: any) {
      console.error('[PRD] Error:', e.message || e)
      streamError.value = e.message || 'PRD generation failed'
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
        break
      case 'stage_complete':
        store.setStageStatus(event.stage, 'done')
        store.setStagePhase('complete')
        if (event.summary) store.setStageOutput(event.stage as Stage, event.summary)
        break
      case 'human_confirm_required':
        store.setAwaitingConfirm(true)
        break
      case 'prd_generate_start':
        store.resetDocContent()
        break
      case 'prd_section':
        store.appendPRDContent(event.content || '')
        store.appendDocContent(event.content || '')
        break
      case 'prd_generate_done':
        store.setDocComplete(event.full_content || '')
        if (event.full_content) store.setStageOutput('analysis', event.full_content)
        break
      case 'doc_chunk':
        store.appendDocContent(event.content || '')
        break
      case 'design_gen_start':
        store.resetDocContent()
        break
      case 'design_gen_done':
        store.setDocComplete(event.full_content || '')
        if (event.full_content) store.setStageOutput('design', event.full_content)
        break
      case 'code_gen_start':
        store.initFileTree(event.files || [])
        break
      case 'file_start':
        store.setCurrentGeneratingFile(event.path)
        break
      case 'file_chunk':
        store.appendFileContent(event.path, event.content || '')
        break
      case 'file_complete':
        store.finalizeFile(event.path)
        break
      case 'tool_call':
        store.addToolTrace({ type: 'call', tool: event.tool, args: event.args, status: 'running' })
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
        break
      case 'code_gen_done':
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
    try {
      const response = await fetch('/api/v1/generation/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          messages: [],
          model: 'glm-5.2',
          generation_id: store.currentGenerationId,
          mode: 'resume',
          component_lib: store.currentLib,
        }),
      })

      if (!response.ok) {
        throw new Error(`Resume failed: ${response.status}`)
      }

      // Read SSE stream for resumed graph events
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
    cancel,
  }
}
