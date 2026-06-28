import { defineStore } from 'pinia';
import { ref, computed } from 'vue';
import type { Message } from '@ai-design/shared';

export const useChatStore = defineStore('chat', () => {
  const currentConversationId = ref<string | null>(null);
  const messages = ref<Message[]>([]);
  const streamingContent = ref('');
  const isStreaming = ref(false);
  const streamError = ref<string | null>(null);
  const inputText = ref('');
  const enableThinking = ref(false);
  const reasoningContent = ref('');
  const isReasoning = ref(false);
  const reasoningStartTime = ref(0);

  const displayMessages = computed<Message[]>(() => {
    if (streamingContent.value) {
      const virtual: Message = {
        id: '__streaming__',
        role: 'assistant',
        content: streamingContent.value,
        created_at: new Date().toISOString(),
        reasoning_content: reasoningContent.value || undefined,
        reasoning_duration_ms: reasoningStartTime.value
          ? Date.now() - reasoningStartTime.value
          : undefined,
      };
      return [...messages.value, virtual];
    }
    // 始终返回新数组引用，确保 Vue v-for 检测到变化
    return [...messages.value];
  });

  function selectConversation(id: string | null, msgs: Message[] = []) {
    currentConversationId.value = id;
    messages.value = msgs;
    streamingContent.value = '';
    isStreaming.value = false;
    streamError.value = null;
    reasoningContent.value = '';
    isReasoning.value = false;
    reasoningStartTime.value = 0;
  }

  function appendMessage(msg: Message) {
    messages.value.push(msg);
  }

  function startStreaming() {
    isStreaming.value = true;
    streamingContent.value = '';
    streamError.value = null;
    reasoningContent.value = '';
    isReasoning.value = false;
    reasoningStartTime.value = 0;
  }

  function appendToken(text: string) {
    streamingContent.value += text;
  }

  function appendReasoning(text: string) {
    if (!isReasoning.value) {
      isReasoning.value = true;
      reasoningStartTime.value = Date.now();
    }
    reasoningContent.value += text;
  }

  function finishReasoning() {
    isReasoning.value = false;
  }

  function getReasoningDuration(): number {
    return reasoningStartTime.value ? Date.now() - reasoningStartTime.value : 0;
  }

  function finishStreaming(messageId: string) {
    if (streamingContent.value) {
      appendMessage({
        id: messageId,
        role: 'assistant',
        content: streamingContent.value,
        created_at: new Date().toISOString(),
        reasoning_content: reasoningContent.value || undefined,
        reasoning_duration_ms: reasoningStartTime.value
          ? Date.now() - reasoningStartTime.value
          : undefined,
      });
    }
    streamingContent.value = '';
    isStreaming.value = false;
    reasoningContent.value = '';
    isReasoning.value = false;
  }

  function setStreamError(err: string) {
    streamError.value = err;
    isStreaming.value = false;
  }

  function cancelStream() {
    isStreaming.value = false;
  }

  function clearInput() {
    inputText.value = '';
  }

  function toggleThinking() {
    enableThinking.value = !enableThinking.value;
  }

  return {
    currentConversationId,
    messages,
    streamingContent,
    isStreaming,
    streamError,
    inputText,
    enableThinking,
    reasoningContent,
    isReasoning,
    reasoningStartTime,
    displayMessages,
    selectConversation,
    appendMessage,
    startStreaming,
    appendToken,
    appendReasoning,
    finishReasoning,
    getReasoningDuration,
    finishStreaming,
    setStreamError,
    cancelStream,
    clearInput,
    toggleThinking,
  };
});
