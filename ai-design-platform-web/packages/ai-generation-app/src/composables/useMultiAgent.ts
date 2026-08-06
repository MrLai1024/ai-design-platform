// src/composables/useMultiAgent.ts
import { ref } from 'vue'
import { useGenerationStore } from '../stores/generation'
import { useStreamChat } from './useStreamChat'
import { handleCodeSSEEvent } from './useCodeStream'
import { generateId } from '@/utils/id'
import type { Stage, E2ECaseResult, ManagerIntent } from '../types/generation'

export function useMultiAgent() {
  const store = useGenerationStore()
  const { send, cancel: cancelStream } = useStreamChat()

  const isTransitioning = ref(false)
  const streamError = ref<string | null>(null)
  // 8.x 增量开发模式: 全程跑在同一 runner 实例 (resume), confirmStage 不得
  // 走 fresh-start 预填路径。
  const isIncremental = ref(false)
  // 10.1: 反馈提交 / 反馈范围确认卡「确认」后的下一次 confirmStage 强制
  // resume 同一 runner — Manager 处置 (重派指令/范围确认卡) 挂起在当前
  // runner 上, fresh-start (新 UUID) 会丢失处置。
  let forceResume = false

  function forceResumeNextConfirm(): void {
    forceResume = true
  }
  let currentAbortController: AbortController | null = null

  /** 读取 SSE 流并按帧分发 graph 事件 (startGraphGeneration / 增量开发共用) */
  async function streamGraphSSE(response: Response): Promise<void> {
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
  }

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
      const resp = await fetch('/api/v1/generation/feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          generation_id: store.currentGenerationId,
          stage: store.stage,
          feedback,
        }),
      })
      if (!resp.ok) throw new Error(`Feedback failed: ${resp.status}`)
      // 10.1: 处置挂起在当前 runner 上 — 后续 confirmStage 必须 resume
      // 同一 runner (fresh-start 新 UUID 会丢失反馈)。
      forceResume = true
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
    isIncremental.value = false
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

  /** 头脑风暴（任务组 3）：跑一轮议程驱动的澄清 — POST /api/v1/generation/brainstorm */
  async function sendBrainstormTurn(text: string, itemId?: string): Promise<void> {
    store.isStreaming = true
    const controller = getAbortController()
    try {
      const resp = await fetch('/api/v1/generation/brainstorm', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text,
          generation_id: store.currentGenerationId || undefined,
          item_id: itemId || undefined,
        }),
        signal: controller.signal,
      })
      if (!resp.ok) throw new Error(`Brainstorm failed: ${resp.status}`)
      const data = await resp.json()
      if (data.generation_id) store.setGenerationId(data.generation_id)
      store.setBrainstormConverged(!!data.converged)
      if (Array.isArray(data.events)) {
        for (const ev of data.events) {
          dispatchGraphEvent(ev._t, ev)
        }
      }
    } catch (e: any) {
      if (e instanceof DOMException && e.name === 'AbortError') return
      streamError.value = e.message || 'Brainstorm failed'
    } finally {
      store.isStreaming = false
    }
  }

  /** 首次提交需求 → 创建头脑风暴会话并输出需求画像（任务组 3） */
  async function startBrainstorm(content: string): Promise<void> {
    isIncremental.value = false
    store.resetAll()
    store.setStage('analysis')
    store.setStageStatus('analysis', 'active')
    store.setStagePhase('qa')
    pushUserMessage(content)
    await sendBrainstormTurn(content)
  }

  /** 启动 graph 流水线 — /api/v1/generation/stream (PRD 在 graph 内流式生成) */
  async function startGraphGeneration(content: string) {
    isIncremental.value = false
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
          model: 'glm-5.2',
          // 头脑风暴会话 id：servicer 据此加载收敛产物（结构化需求/决策/假设）
          generation_id: store.currentGenerationId || undefined,
        }),
      })

      if (!response.ok) {
        const errText = await response.text()
        throw new Error(`Graph error: ${response.status} ${errText}`)
      }

      await streamGraphSSE(response)
    } catch (e: any) {
      streamError.value = e.message || 'Graph generation failed'
    } finally {
      store.isStreaming = false
      store.docIsStreaming = false
      isTransitioning.value = false
    }
  }

  /** 8.x 增量开发入口：对已有应用（同 generation_id 的 .ai-memory）发起
   * 增量开发 — 服务端加载应用记忆 → 新需求 diff → 变更 manifest → 用例处置
   * → 增量流水线。全程跑在同一 runner 实例（后续确认走 resume）。 */
  async function startIncrementalGeneration(content: string): Promise<void> {
    const appId = store.currentGenerationId
    isIncremental.value = true
    store.resetAll()
    if (appId) store.setGenerationId(appId)
    store.setStage('analysis')
    store.setStageStatus('analysis', 'active')
    store.setStagePhase('generating')
    pushUserMessage(content)
    store.isStreaming = true
    isTransitioning.value = true
    try {
      const response = await fetch('/api/v1/generation/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          messages: [{ role: 'user', content }],
          model: 'glm-5.2',
          generation_id: appId || undefined,
          incremental: true,
        }),
      })
      if (!response.ok) {
        const errText = await response.text()
        throw new Error(`Incremental error: ${response.status} ${errText}`)
      }
      await streamGraphSSE(response)
    } catch (e: any) {
      streamError.value = e.message || 'Incremental generation failed'
    } finally {
      store.isStreaming = false
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
      case 'manager_verdict':
        // 9.3 (C1): 把关裁决留痕 — redo/rollback 时清空前端该阶段产物副本
        // (后端已清), 下次确认走 resume 同一 runner 携带恢复计数与重派反馈,
        // 不再把失败产物 prefill 进新 runner。
        store.setLastVerdict(event.stage as string, event.decision)
        if (event.decision === 'redo' || event.decision === 'rollback') {
          store.clearFailedStageOutput(event.stage as string)
        }
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
      case 'e2e_cases_gen_start':
        store.resetDocContent()
        break
      case 'e2e_cases_gen_done':
        store.setE2ECasesDoc(event.full_content || '')
        store.setDocComplete(event.full_content || '')
        // 6.1: DSL 用例是规范产物 —— 面板用例清单直接消费 cases（覆盖矩阵卡片
        // 走 manager_message）
        if (Array.isArray(event.cases)) {
          store.setE2ETestCases(event.cases)
        }
        break
      case 'e2e_execute_start':
        store.setE2ETestCases(event.test_cases || [])
        store.clearE2EResults()
        store.setE2EDiagnosis(null)
        break
      case 'e2e_case_start':
        store.setCurrentE2ECase(event.case_id)
        break
      case 'e2e_case_result':
        store.addE2EResult({
          caseId: event.case_id, passed: event.passed,
          error: event.error, screenshot: event.screenshot,
          status: event.status, evidence: event.evidence,
        })
        break
      case 'e2e_diagnosis':
        // 6.4: Test Diagnoser 三方分类结果
        store.setE2EDiagnosis(event)
        break
      case 'e2e_complete':
        store.setStageStatus('e2e', event.passed ? 'done' : 'pending')
        store.e2eRunning = false
        if (event.diagnosis) store.setE2EDiagnosis(event.diagnosis)
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
        // 2.5: 把关熔断 → 对话框求援消息（诊断 + 继续自主/转人工），替代右侧 banner
        store.setNeedsManualReview(true)
        store.setLoopBreakReason(event.reason || null)
        store.addManagerCard({
          card: 'diagnosis_card',
          title: '需要你的决策',
          content: `自动流程遇到问题：${event.reason || '未知原因'}\n\nManager 已暂停，请你决定如何继续。`,
          options: ['继续自主', '转人工'],
          data: { node: event.stage || undefined, reason: event.reason || '' },
          stage: event.stage as Stage,
        })
        break
      case 'manager_message':
        // 2.2: Manager 结构化消息卡片（summary/verdict/diagnosis/confirm/proposal/coverage_matrix）
        store.addManagerCard({
          card: event.card,
          title: event.title,
          content: event.content,
          options: event.options,
          data: event.data,
          stage: event.stage as Stage,
        })
        break
      case 'complete':
      case 'done':
        break
      case 'error':
        streamError.value = event.message || 'Unknown error'
        break
    }
  }

  /** 2.3: Manager 自判意图 — 轻量 LLM 调用（/api/v1/generation/intent），失败回退 reply_qa */
  async function classifyUserIntent(text: string): Promise<ManagerIntent> {
    try {
      const resp = await fetch('/api/v1/generation/intent', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text,
          stage: store.stage,
          generation_id: store.currentGenerationId,
        }),
      })
      if (!resp.ok) return 'reply_qa'
      const data = await resp.json()
      const intents: ManagerIntent[] = ['reply_qa', 'proceed', 'feedback', 'escalate', 'ask_why']
      return intents.includes(data.intent) ? data.intent : 'reply_qa'
    } catch (e) {
      console.warn('[intent] classify failed, fallback to reply_qa', e)
      return 'reply_qa'
    }
  }

  function pushUserMessage(content: string): void {
    store.addMessage({
      id: generateId(),
      role: 'user',
      content,
      codeBlocks: [],
      timestamp: Date.now(),
      isStreaming: false,
    })
  }

  function pushAssistantMessage(content: string): void {
    store.addMessage({
      id: generateId(),
      role: 'assistant',
      content,
      codeBlocks: [],
      timestamp: Date.now(),
      isStreaming: false,
    })
  }

  /** 2.3: 按 Manager 自判意图分流用户输入（reply_qa 由调用方走原有 QA 对话路径） */
  async function routeUserMessage(content: string): Promise<ManagerIntent> {
    const intent = await classifyUserIntent(content)
    switch (intent) {
      case 'proceed':
        pushUserMessage(content)
        await confirmStage(store.stage)
        break
      case 'feedback':
        pushUserMessage(content)
        await sendFeedback(content)
        break
      case 'escalate':
        pushUserMessage(content)
        store.setManualMode(true)
        pushAssistantMessage('已切换为人工接管模式（占位实现，完整接管流程将在后续版本提供）。')
        break
      case 'ask_why':
        pushUserMessage(content)
        pushAssistantMessage(
          `Manager 决策依据模块正在建设中。关于「${content}」，后续版本将结合评估证据与运行记忆给出完整解释。`,
        )
        break
      case 'reply_qa':
      default:
        break
    }
    return intent
  }

  /** 8.x 增量模式 resume: 全程同一 runner 实例 (graph 入口逐级确认
   * diff → manifest → 处置清单), 不携带预填消息。extra 可追加 metadata
   * (如 regen=true)。 */
  async function resumeIncremental(extra: Record<string, any> = {}): Promise<void> {
    if (isTransitioning.value) return  // review M3: 双确认防重入
    isTransitioning.value = true
    store.setAwaitingConfirm(false)
    const body: Record<string, any> = {
      model: 'glm-5.2',
      mode: 'resume',
      messages: [],
      generation_id: store.currentGenerationId,
      // 兜底: runner 丢失 (刷新) 时仍回到增量入口而非误跑全新流水线
      incremental: true,
      ...extra,
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
      await streamGraphSSE(response)
    } catch (e: any) {
      streamError.value = e.message || 'Confirm failed'
    } finally {
      isTransitioning.value = false
    }
  }

  /** 8.x (review I1): 增量确认卡「重新生成」— 服务端清除当前待确认级产物,
   * 从该级重新计算 (diff/manifest/处置均可重跑)。 */
  async function regenIncrementalStep(): Promise<void> {
    await resumeIncremental({ regen: true })
  }

  async function confirmStage(stage: Stage) {
    if (isTransitioning.value) return  // review M3: 双确认防重入
    isTransitioning.value = true
    store.setAwaitingConfirm(false)

    // 10.1: 反馈提交 / 反馈范围确认卡「确认」→ 本次 confirmStage 强制 resume
    // 同一 runner (Manager 处置挂起在当前 runner, fresh-start 新 UUID 会丢失)。
    const forceResumeNow = forceResume
    forceResume = false

    // 8.x 增量模式: 全程 resume 同一 runner 实例 (graph 入口逐级确认
    // diff → manifest → 处置清单), 不携带预填消息。
    if (isIncremental.value) {
      await resumeIncremental()
      return
    }

    // First transitions: PRD done (analysis) or design done (design)
    // Graph hasn't started yet, so send pre-filled state
    const needsFreshStart = stage === 'analysis' || stage === 'design' || stage === 'code'
    // 9.3 (C1): 该阶段最近一次把关为 redo/rollback → 必须 resume 同一 runner
    // (generation_id 已由 meta 事件记录): 恢复计数/重派反馈/证据随 runner 状态
    // 延续, 阶段重跑 (阶段 1/2 重生成、阶段 4 重审) 而非带失败产物重新起跑。
    const failedVerdict = store.lastVerdicts[stage] === 'redo' || store.lastVerdicts[stage] === 'rollback'
    const body: Record<string, any> = {
      model: 'glm-5.2',

      mode: 'graph',
    }

    // 10.1: 反馈后的 confirmStage → resume 同一 runner (Manager 处置消费)。
    if (forceResumeNow) {
      body.messages = []
      body.generation_id = store.currentGenerationId
      body.mode = 'resume'
    } else if (needsFreshStart && !failedVerdict) {
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
    } else {
      // Resume graph for code+ (and for gate-failed manual stages, C1)
      body.messages = []
      body.generation_id = store.currentGenerationId
      body.mode = 'resume'
      // 6.x (review I3): 显式 E2E 用例确认标记 —— 仅 E2EStagePanel 的
      // 「确认测试用例」路径携带；聊天 proceed 等其它 resume 不携带，
      // 服务端据此避免把「继续」误判为用例确认。
      if (stage === 'e2e' && store.e2eUserConfirmed) {
        body.e2e_confirmed = true
      }
    }
    console.log('[confirmStage] body=', JSON.stringify({...body, messages: body.messages?.length || 0}))

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

  /** 6.3/6.4: 整轮执行完成后一次性提交结果 → gateway → AI service
   * ResumeAfterE2E（Test Diagnoser 三方分类 → e2e gate 路由）。
   * 响应为 SSE GraphEvents（manager 裁决 / 诊断卡片 / e2e_complete），
   * 逐帧分发到 store。 */
  async function submitE2EResults(results: E2ECaseResult[]) {
    isTransitioning.value = true
    try {
      const controller = getAbortController()
      const response = await fetch('/api/v1/e2e/result', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          generation_id: store.currentGenerationId,
          results: results.map((r) => ({
            case_id: r.caseId,
            passed: r.passed,
            error: r.error,
            status: r.status || (r.passed ? 'passed' : 'failed'),
            screenshot: r.screenshot,
            evidence: r.evidence ? {
              dom_snapshot: r.evidence.dom_snapshot,
              console_errors: r.evidence.console_errors,
              network_errors: r.evidence.network_errors,
              screenshot_note: r.evidence.screenshot_note,
            } : undefined,
          })),
        }),
        signal: controller.signal,
      })
      if (!response.ok) throw new Error(`E2E result submit failed: ${response.status}`)

      if (response.body) {
        const reader = response.body.getReader()
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
      }
    } catch (e: any) {
      streamError.value = e.message || 'E2E result submit failed'
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
    startBrainstorm,
    sendBrainstormTurn,
    startGraphGeneration,
    startIncrementalGeneration,
    isIncremental,
    regenIncrementalStep,
    confirmStage,
    forceResumeNextConfirm,
    submitE2EResults,
    sendFeedback,
    classifyUserIntent,
    routeUserMessage,
    cancelGeneration,
    cancel,
  }
}
