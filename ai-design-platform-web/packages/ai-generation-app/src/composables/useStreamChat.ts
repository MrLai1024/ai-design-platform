// src/composables/useStreamChat.ts
import { ref } from 'vue'
import { useGenerationStore } from '@/stores/generation'
import { useComponentDocs } from './useComponentDocs'
import type { ChatMessage, Stage } from '@/types/generation'

function generateId(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 9)
}

export interface StreamSendOptions {
  /** 用户输入的文本内容（需求分析阶段使用） */
  content?: string
  /** 外部传入的完整 messages 数组（详细设计/代码实现阶段使用），优先级高于 content */
  messages?: Array<{ role: string; content: string }>
  /** 自定义系统提示词（需求分析等阶段使用），仅在未传 messages 时生效 */
  systemPrompt?: string
  /** 消息所属阶段 */
  stage?: 'analysis' | 'design' | 'code'
}

export function useStreamChat() {
  const store = useGenerationStore()
  const { getSystemPrompt } = useComponentDocs()
  const error = ref<string | null>(null)
  let abortController: AbortController | null = null

  async function send(opts: StreamSendOptions): Promise<void> {
    const { content, messages: externalMessages, systemPrompt: customSystemPrompt, stage: msgStage } = opts
    error.value = null

    // 1. 添加用户消息（仅当有 content 时）
    if (content) {
      const userMsg: ChatMessage = {
        id: generateId(),
        role: 'user',
        content,
        codeBlocks: [],
        timestamp: Date.now(),
        isStreaming: false,
        stage: msgStage,
      }
      store.addMessage(userMsg)
    }

    // 2. 创建空的 assistant 消息
    const assistantMsg: ChatMessage = {
      id: generateId(),
      role: 'assistant',
      content: '',
      codeBlocks: [],
      timestamp: Date.now(),
      isStreaming: true,
      stage: msgStage,
    }
    store.addMessage(assistantMsg)
    store.isStreaming = true

    // 3. 构建请求 body
    abortController = new AbortController()

    const requestMessages = externalMessages ?? [
      { role: 'system', content: customSystemPrompt || getSystemPrompt() },
      ...store.messages
        .filter((m) => !m.isStreaming)
        .map((m) => ({ role: m.role, content: m.content })),
    ]

    try {
      const response = await fetch('/api/v1/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          messages: requestMessages,
          model: 'glm-5.2',
          stream: true,
        }),
        signal: abortController.signal,
      })

      if (!response.ok) {
        throw new Error(`后端返回错误: ${response.status} ${response.statusText}`)
      }

      const reader = response.body!.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let reasoningStartTime = 0

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        // SSE 帧以 \n\n 分隔（匹配后端 writeSSE 的格式）
        const frames = buffer.split('\n\n')
        buffer = frames.pop() || ''

        for (const frame of frames) {
          if (!frame.trim()) continue
          // 提取 data: 行
          const dataLine = frame
            .split('\n')
            .find((l) => l.startsWith('data:'))
          if (!dataLine) continue

          const raw = dataLine.slice(5).trimStart()
          if (!raw) continue

          // [DONE] 标记 — 流结束
          if (raw === '[DONE]') continue

          try {
            const event = JSON.parse(raw)
            const eventType: string = event._t

            switch (eventType) {
              case 'meta':
                if (event.generation_id) {
                  store.setGenerationId(event.generation_id)
                }
                break

              case 'token':
                if (event.text) {
                  store.appendToLastMessage(event.text)
                  // 让出主线程，使 Vue 有机会渲染本次 token
                  await new Promise((r) => setTimeout(r, 0))
                }
                break

              case 'reasoning':
                if (!reasoningStartTime) reasoningStartTime = Date.now()
                if (event.text) {
                  // 排除 GLM API 可能返回的占位符
                  const cleaned = event.text.replace(/^(\s*\[思考中\]\s*)+$/, '')
                  if (cleaned.trim()) {
                    store.appendReasoning(cleaned)
                  }
                }
                break

              case 'complete':
                if (reasoningStartTime) {
                  store.finishReasoning()
                }
                break

              case 'error':
                error.value = event.message || event.error || '未知错误'
                break

              case 'stage_start':
                store.setStageStatus(event.stage, 'active')
                store.setStage(event.stage as Stage)
                if (event.phase) {
                  store.setStagePhase(event.phase)
                }
                break

              case 'stage_complete':
                store.setStageStatus(event.stage, 'done')
                store.setStagePhase('complete')
                if (event.summary) {
                  store.setStageOutput(event.stage as Stage, event.summary)
                }
                break

              case 'stage_rollback':
                store.addRollbackEvent({
                  from: event.from,
                  to: event.to,
                  reason: event.reason,
                  failedCases: event.failed_cases,
                })
                store.setStage(event.to as Stage)
                store.setStageStatus(event.to, 'active')
                break

              case 'e2e_start':
                store.setE2ETestCases(event.test_cases || [])
                store.clearE2EResults()
                store.setStageStatus('e2e', 'active')
                break

              case 'e2e_case_result':
                store.addE2EResult({
                  caseId: event.case_id,
                  passed: event.passed,
                  error: event.error,
                  screenshot: event.screenshot,
                })
                break

              case 'e2e_complete':
                store.setStageStatus('e2e', event.passed ? 'done' : 'pending')
                store.e2eRunning = false
                break

              case 'human_confirm_required':
                store.setAwaitingConfirm(true)
                break

              case 'loop_warning':
                console.warn(`Loop warning: ${event.reason}`)
                break

              case 'loop_break':
                store.setNeedsManualReview(true)
                store.setLoopBreakReason(event.reason)
                break

              // --- 需求分析事件 ---

              case 'requirement_mode_set':
                if (event.mode && store.requirementsState) {
                  store.requirementsState.mode = event.mode
                  store.requirementsState.version = event.version ?? 0
                }
                break

              case 'requirement_layer_start':
                if (store.requirementsState) {
                  store.requirementsState.layer = event.layer
                  if (event.layer) {
                    store.requirementsState.layer_status[String(event.layer)] = 'active'
                  }
                }
                break

              case 'requirement_card_update':
                if (event.fields) {
                  store.setRequirementsState(event.fields)
                }
                break

              case 'requirement_question':
                // Questions are rendered via ChatPanel messages + card_update data
                break

              case 'requirement_layer_done':
                if (store.requirementsState && event.layer) {
                  store.requirementsState.layer_status[String(event.layer)] = 'done'
                }
                break

              case 'prd_generate_start':
                store.setAnalysisPanelMode('prd')
                store.prdStreamingContent = ''
                break

              case 'prd_section':
                store.appendPRDContent(event.content || '')
                store.appendDocContent(event.content || '')
                break

              case 'prd_section_complete':
                store.setPRDCurrentSection(null)
                break

              case 'prd_diff':
                store.appendPRDDiff(event.change || 'added', event.section || '', event.content || '')
                break

              case 'prd_diff_done':
                store.setPRDVersion(event.version ?? 0)
                break

              case 'prd_generate_done':
                store.setPRDVersion(event.version ?? 0)
                store.setPRDComplete(event.full_content || '')
                store.setDocComplete(event.full_content || '')
                if (event.full_content) {
                  store.setStageOutput('analysis', event.full_content)
                }
                break

              // ── 流式文档（统一 doc_chunk）──
              case 'doc_chunk':
                store.appendDocContent(event.content || '')
                break

              // ── Design 阶段 ──
              case 'design_gen_start':
                store.resetDocContent()
                break

              case 'design_gen_done':
                store.setDocComplete(event.full_content || '')
                if (event.full_content) {
                  store.setStageOutput('design', event.full_content)
                }
                break

              // ── Code 阶段 ──
              case 'code_gen_start':
                store.initFileTree(event.files || [])
                store.docIsStreaming = true
                break

              case 'file_start':
                store.setCurrentGeneratingFile(event.path)
                break

              case 'file_chunk':
                store.appendFileContent(event.path, event.content || '')
                break

              case 'file_complete':
                store.finalizeFile(event.path)
                store.setCurrentGeneratingFile(null)
                break

              case 'tool_call': {
                store.addToolTrace({
                  type: 'call',
                  tool: event.tool,
                  args: event.args,
                  status: 'running',
                })
                break
              }

              case 'tool_result': {
                const traces = store.toolTraces
                for (let i = traces.length - 1; i >= 0; i--) {
                  if (traces[i]!.tool === event.tool && traces[i]!.status === 'running') {
                    store.updateToolTrace(traces[i]!.id, {
                      type: 'result',
                      status: event.ok ? 'done' : 'error',
                      summary: event.summary || (event.ok ? 'Done' : 'Error'),
                    })
                    break
                  }
                }
                break
              }

              case 'code_gen_done':
                store.setCodeGenDone(event.total_files || 0, event.compile_errors || 0)
                break

              // ── Review 阶段 ──
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

              case 'review_fix_start':
                // Auto-fixing — switching back to code stage
                break

              case 'review_fix_done':
                // Fix complete
                break

              // ── E2E 阶段 ──
              case 'e2e_cases_gen_start':
                store.resetDocContent()
                break

              case 'e2e_cases_gen_done':
                store.setE2ECasesDoc(event.full_content || '')
                store.setDocComplete(event.full_content || '')
                break

              case 'e2e_execute_start':
                store.clearE2EResults()
                break

              case 'e2e_case_start':
                store.setCurrentE2ECase(event.case_id)
                break

              case 'e2e_execute_done':
                store.setE2EComplete({
                  total: event.total || 0,
                  passed: event.passed || 0,
                  failed: event.failed || 0,
                })
                break

              case 'graph_complete':
                store.setStage('done')
                break
            }
          } catch {
            // JSON 解析失败，跳过该帧
          }
        }
      }
    } catch (e: unknown) {
      if (e instanceof DOMException && e.name === 'AbortError') {
        return // 用户取消，不标记中断
      }
      error.value = e instanceof Error ? e.message : '未知错误'
      // 标记消息为中断，后续可续写
      const last = store.lastAssistantMessage
      if (last) {
        last.interrupted = true
      }
      store.appendToLastMessage(`\n\n> ⚠️ 生成中断: ${error.value}`)
    } finally {
      store.finalizeLastMessage()
      abortController = null
    }
  }

  function cancel(): void {
    abortController?.abort()
    store.isStreaming = false
  }

  return { send, cancel, error, isStreaming: () => store.isStreaming }
}
