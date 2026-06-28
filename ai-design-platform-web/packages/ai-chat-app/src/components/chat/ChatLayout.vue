<template>
  <div class="flex h-screen bg-gray-950 text-gray-200">
    <ConversationSidebar
      :active-id="chatStore.currentConversationId"
      @select="handleSelect"
      @new-chat="handleNewChat"
    />
    <div class="flex-1 flex flex-col min-w-0">
      <ChatWindow
        @send="handleSend"
        @stop="handleStop"
        @retry="handleRetry"
        @regenerate="handleRegenerate"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue';
import { useRouter } from 'vue-router';
import { useChatStore } from '@/stores/chatStore';
import { useConversationStore } from '@/stores/conversationStore';
import {
  useChatStream,
  listConversations,
  getConversation,
  createConversation,
  type StreamCallbacks,
} from '@ai-design/shared';
import type { Conversation, ConversationListItem } from '@ai-design/shared';
import ConversationSidebar from './ConversationSidebar.vue';
import ChatWindow from './ChatWindow.vue';

const router = useRouter();
const chatStore = useChatStore();
const convStore = useConversationStore();

const MODEL = 'glm-5.2';

const callbacks: StreamCallbacks = {
  onMeta(meta) {
    console.log('[chat] meta:', meta);
  },
  onToken(text) {
    chatStore.appendToken(text);
  },
  onReasoning(text) {
    chatStore.appendReasoning(text);
  },
  onToolCall(tool) {
    console.log('[chat] tool_call:', tool);
  },
  onComplete(finishReason) {
    console.log('[chat] complete:', finishReason);
  },
  onError(message) {
    chatStore.setStreamError(message);
  },
  onDone() {
    const msgId = crypto.randomUUID();
    chatStore.finishStreaming(msgId);
    const convId = chatStore.currentConversationId;
    if (convId) {
      convStore.incrementMsgCount(convId);
      refreshConversationList();
    }
  },
};

const { start: startStream, cancel: cancelStream } = useChatStream(callbacks);

async function refreshConversationList() {
  const res = await listConversations();
  const data = res as unknown as { conversations: ConversationListItem[] };
  if (data?.conversations) {
    convStore.setConversations(data.conversations);
  }
}

async function handleSend(content: string) {
  chatStore.clearInput();

  let convId = chatStore.currentConversationId;
  if (!convId) {
    const title = content.length > 30 ? content.slice(0, 30) + '...' : content;
    // Use the store action to create + optimistically add
    const conv = await createConversation(title);
    const created = (conv as unknown as { id?: string; title?: string; created_at?: string; updated_at?: string });
    if (!created?.id) return;
    convId = created.id;
    chatStore.currentConversationId = convId;
    convStore.addConversation({
      id: created.id,
      title: created.title || title,
      msg_count: 0,
      created_at: created.created_at || new Date().toISOString(),
      updated_at: created.updated_at || new Date().toISOString(),
    });
    router.replace(`/chat/${convId}`);
  }

  const userMsgId = crypto.randomUUID();
  chatStore.appendMessage({
    id: userMsgId,
    role: 'user',
    content,
    created_at: new Date().toISOString(),
  });

  chatStore.startStreaming();
  startStream(convId, MODEL, content, chatStore.enableThinking);
}

function handleStop() {
  cancelStream();
  chatStore.cancelStream();
}

async function handleSelect(convId: string) {
  const conv = await getConversation(convId) as unknown as Conversation;
  if (conv) {
    chatStore.selectConversation(convId, conv.messages || []);
    router.replace(`/chat/${convId}`);
  }
}

function handleNewChat() {
  chatStore.selectConversation(null, []);
  router.replace('/chat');
}

async function handleRetry() {
  const lastUserMsg = [...chatStore.messages].reverse().find((m) => m.role === 'user');
  if (lastUserMsg && chatStore.currentConversationId) {
    chatStore.streamError = null as any;
    chatStore.startStreaming();
    startStream(chatStore.currentConversationId!, MODEL, lastUserMsg.content, chatStore.enableThinking);
  }
}

async function handleRegenerate(msgId: string) {
  const idx = chatStore.messages.findIndex((m) => m.id === msgId);
  if (idx === -1) return;
  let lastUserMsg: { content: string } | null = null;
  for (let i = idx - 1; i >= 0; i--) {
    if (chatStore.messages[i].role === 'user') {
      lastUserMsg = chatStore.messages[i];
      break;
    }
  }
  if (lastUserMsg && chatStore.currentConversationId) {
    chatStore.startStreaming();
    startStream(chatStore.currentConversationId!, MODEL, lastUserMsg.content, chatStore.enableThinking);
  }
}

onMounted(async () => {
  await refreshConversationList();
});
</script>
