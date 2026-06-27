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

  const displayMessages = computed<Message[]>(() => {
    if (streamingContent.value) {
      const virtual: Message = {
        id: '__streaming__',
        role: 'assistant',
        content: streamingContent.value,
        created_at: new Date().toISOString(),
      };
      return [...messages.value, virtual];
    }
    return messages.value;
  });

  function selectConversation(id: string | null, msgs: Message[] = []) {
    currentConversationId.value = id;
    messages.value = msgs;
    streamingContent.value = '';
    isStreaming.value = false;
    streamError.value = null;
  }

  function appendMessage(msg: Message) {
    messages.value.push(msg);
  }

  function startStreaming() {
    isStreaming.value = true;
    streamingContent.value = '';
    streamError.value = null;
  }

  function appendToken(text: string) {
    streamingContent.value += text;
  }

  function finishStreaming(messageId: string) {
    if (streamingContent.value) {
      appendMessage({
        id: messageId,
        role: 'assistant',
        content: streamingContent.value,
        created_at: new Date().toISOString(),
      });
    }
    streamingContent.value = '';
    isStreaming.value = false;
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

  return {
    currentConversationId,
    messages,
    streamingContent,
    isStreaming,
    streamError,
    inputText,
    displayMessages,
    selectConversation,
    appendMessage,
    startStreaming,
    appendToken,
    finishStreaming,
    setStreamError,
    cancelStream,
    clearInput,
  };
});
