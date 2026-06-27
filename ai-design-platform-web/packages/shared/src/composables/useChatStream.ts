import { ref, readonly, type Ref } from 'vue';
import { streamChat, cancelGeneration } from '../api/chat';

export interface StreamCallbacks {
  onToken: (text: string, index: number) => void;
  onMeta: (meta: { generation_id: string; conversation_id?: string; message_id?: string }) => void;
  onToolCall: (tool: { id: string; name: string; arguments: string }) => void;
  onComplete: (finishReason: string) => void;
  onError: (message: string, code?: string) => void;
  onDone: () => void;
}

const MAX_RETRIES = 2;
const RETRY_DELAY_MS = 1000;

/**
 * SSE 流式聊天 composable。
 * 管理 SSE 连接生命周期：启动、接收、取消、重连。
 */
export function useChatStream(callbacks: StreamCallbacks) {
  const isStreaming = ref(false);
  const error = ref<string | null>(null);
  const generationId = ref<string | null>(null);

  let abortController: AbortController | null = null;
  let retryCount = 0;

  async function start(conversationId: string, model: string, content: string) {
    isStreaming.value = true;
    error.value = null;
    retryCount = 0;

    await connect(conversationId, model, content);
  }

  async function connect(conversationId: string, model: string, content: string) {
    abortController = new AbortController();

    try {
      const response = await streamChat(conversationId, model, content);
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const reader = response.body?.getReader();
      if (!reader) throw new Error('ReadableStream not supported');

      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split('\n\n');
        buffer = parts.pop() || '';

        for (const part of parts) {
          if (!part.trim()) continue;
          const event = parseSSEEvent(part);
          if (!event) continue;

          switch (event.type) {
            case 'meta':
              generationId.value = event.generation_id as string;
              callbacks.onMeta({
                generation_id: event.generation_id as string,
                conversation_id: event.conversation_id as string | undefined,
                message_id: event.message_id as string | undefined,
              });
              break;
            case 'token':
              callbacks.onToken(event.text as string, event.index as number);
              break;
            case 'tool_call':
              callbacks.onToolCall({
                id: event.id as string,
                name: event.name as string,
                arguments: event.arguments as string,
              });
              break;
            case 'complete':
              callbacks.onComplete(event.finish_reason as string);
              break;
            case 'error':
              callbacks.onError(event.message as string, event.code as string | undefined);
              break;
            case 'done':
              callbacks.onDone();
              break;
          }
        }
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Unknown error';
      if (retryCount < MAX_RETRIES) {
        retryCount++;
        await new Promise((r) => setTimeout(r, RETRY_DELAY_MS));
        await connect(conversationId, model, content);
        return;
      }
      error.value = msg;
      callbacks.onError(msg);
    } finally {
      isStreaming.value = false;
    }
  }

  function cancel() {
    abortController?.abort();
    if (generationId.value) {
      cancelGeneration(generationId.value).catch(() => {
        // 取消失败不阻塞
      });
    }
    isStreaming.value = false;
  }

  return {
    start,
    cancel,
    isStreaming: readonly(isStreaming) as Ref<boolean>,
    error: readonly(error) as Ref<string | null>,
    generationId: readonly(generationId) as Ref<string | null>,
  };
}

// ── SSE 帧解析（导出以便测试）──

interface ParsedSSEEvent {
  type: string;
  [key: string]: unknown;
}

export function parseSSEEvent(raw: string): ParsedSSEEvent | null {
  let eventType = '';
  let dataStr = '';

  for (const line of raw.split('\n')) {
    if (line.startsWith('event: ')) {
      eventType = line.slice(7).trim();
    } else if (line.startsWith('data: ')) {
      dataStr = line.slice(6);
    }
  }

  if (!eventType || !dataStr) return null;

  if (eventType === 'done') {
    return { type: 'done' };
  }

  try {
    const parsed = JSON.parse(dataStr);
    return { type: eventType, ...parsed };
  } catch {
    return null;
  }
}
