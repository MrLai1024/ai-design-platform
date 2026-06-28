<template>
  <div class="flex flex-col h-full bg-gray-950">
    <div
      v-if="chatStore.streamError"
      class="px-4 py-2 bg-red-900/50 border-b border-red-800 text-red-300 text-sm flex items-center justify-between"
    >
      <span>{{ chatStore.streamError }}</span>
      <button
        class="text-red-400 hover:text-red-300 underline ml-4"
        @click="$emit('retry')"
      >
        重试
      </button>
    </div>

    <div
      ref="scrollContainer"
      class="flex-1 overflow-y-auto px-4 py-6"
      @scroll="autoScroll.onScroll"
    >
      <div class="max-w-4xl mx-auto space-y-1">
        <EmptyState
          v-if="chatStore.displayMessages.length === 0"
          title="开始对话"
          subtitle="在下方输入你的问题"
        />

        <ChatMessage
          v-for="msg in chatStore.displayMessages"
          :key="msg.id"
          :message="msg"
          :is-streaming="msg.id === '__streaming__'"
          @regenerate="handleRegenerate(msg.id)"
        />
      </div>
    </div>

    <MessageInput
      v-model="chatStore.inputText"
      :is-streaming="chatStore.isStreaming"
      :enable-thinking="chatStore.enableThinking"
      @send="handleSend"
      @stop="$emit('stop')"
      @toggle-thinking="chatStore.toggleThinking()"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue';
import { useChatStore } from '@/stores/chatStore';
import { useAutoScroll } from '@/composables/useAutoScroll';
import ChatMessage from './ChatMessage.vue';
import MessageInput from './MessageInput.vue';
import EmptyState from './EmptyState.vue';

const emit = defineEmits<{
  send: [content: string];
  stop: [];
  retry: [];
  regenerate: [messageId: string];
}>();

const chatStore = useChatStore();

const scrollContainer = ref<HTMLElement | null>(null);
const scrollDep = computed(() => ({
  len: chatStore.displayMessages.length,
  streaming: chatStore.streamingContent.length,
}));

const autoScroll = useAutoScroll(scrollContainer, scrollDep);

function handleSend(content: string) {
  emit('send', content);
}

function handleRegenerate(msgId: string) {
  if (msgId === '__streaming__') return;
  emit('regenerate', msgId);
}

onMounted(() => {
  autoScroll.forceScrollToBottom();
});
</script>
