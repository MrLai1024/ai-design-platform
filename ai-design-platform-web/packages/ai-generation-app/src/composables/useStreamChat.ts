// src/composables/useStreamChat.ts
import { ref } from 'vue'
import { useGenerationStore } from '@/stores/generation'
import { useComponentDocs } from './useComponentDocs'
import type { ChatMessage, ComponentLibrary } from '@/types/generation'

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
  /** 消息所属阶段 */
  stage?: 'analysis' | 'design' | 'code'
}

export function useStreamChat() {
  const store = useGenerationStore()
  const { getSystemPrompt } = useComponentDocs()
  const error = ref<string | null>(null)
  let abortController: AbortController | null = null

  async function send(opts: StreamSendOptions): Promise<void> {
    const { content, lib, messages: externalMessages, stage: msgStage } = opts
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
    const systemPrompt = getSystemPrompt()

    const requestMessages = externalMessages ?? [
      { role: 'system', content: systemPrompt },
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

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          try {
            const event = JSON.parse(line.slice(6))
            if (event.content) {
              store.appendToLastMessage(event.content)
            }
            if (event.error) {
              error.value = event.error
            }
          } catch {
            // JSON 解析失败，跳过该行
          }
        }
      }
    } catch (e: unknown) {
      if (e instanceof DOMException && e.name === 'AbortError') {
        return // 用户取消
      }
      error.value = e instanceof Error ? e.message : '未知错误'
      store.appendToLastMessage(`\n\n> ⚠️ 生成失败: ${error.value}`)
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
