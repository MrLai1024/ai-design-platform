// src/composables/useStreamChat.ts
import { ref } from 'vue'
import { useGenerationStore } from '@/stores/generation'
import { useComponentDocs } from './useComponentDocs'
import type { ChatMessage, ComponentLibrary, Stage } from '@/types/generation'

function generateId(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 9)
}

export interface StreamSendOptions {
  /** 用户输入的文本内容（需求分析阶段使用） */
  content?: string
  /** 组件库 */
  lib?: ComponentLibrary
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
    const { content, lib, messages: externalMessages, systemPrompt: customSystemPrompt, stage: msgStage } = opts
    error.value = null
    if (lib) store.setCurrentLib(lib)

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
                break

              case 'stage_complete':
                store.setStageStatus(event.stage, 'done')
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
                // Paused — UI shows confirm button
                break

              case 'loop_warning':
                console.warn(`Loop warning: ${event.reason}`)
                break

              case 'loop_break':
                store.setNeedsManualReview(true)
                store.setLoopBreakReason(event.reason)
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
