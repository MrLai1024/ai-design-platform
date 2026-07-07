<template>
  <div :class="['flex mb-4', isUser ? 'justify-end' : 'justify-start']">
    <div
      :class="[
        'max-w-[80%] rounded-lg px-4 py-3 relative group',
        isUser
          ? 'bg-indigo-600 text-white'
          : 'bg-gray-800 text-gray-200',
      ]"
    >
      <!-- 思考过程可折叠区域 -->
      <div
        v-if="hasReasoning"
        class="mb-3 border border-gray-700 rounded-md overflow-hidden"
      >
        <button
          class="w-full flex items-center gap-1.5 px-3 py-1.5 text-xs text-gray-400 hover:bg-gray-750 transition-colors"
          @click="reasoningExpanded = !reasoningExpanded"
        >
          <span class="text-sm">🧠</span>
          <span v-if="isStreaming && reasoningContent === ''">思考中...</span>
          <span v-else-if="isStreaming && reasoningContent !== ''">思考中...</span>
          <span v-else>思考过程 ({{ formattedDuration }})</span>
          <span class="ml-auto text-gray-600">{{ reasoningExpanded ? '▸ 收起' : '▸ 展开' }}</span>
        </button>
        <div
          v-show="reasoningExpanded"
          class="px-3 py-2 bg-gray-900/50 text-gray-400 text-xs font-mono leading-relaxed max-h-48 overflow-y-auto whitespace-pre-wrap"
        >
          {{ reasoningContent || '...' }}
        </div>
      </div>

      <!-- 正文内容 -->
      <MarkdownRenderer v-if="!isUser" :content="message.content || ''" />
      <p v-else class="whitespace-pre-wrap text-sm">{{ message.content }}</p>

      <span
        v-if="isStreaming"
        class="inline-block w-0.5 h-4 bg-indigo-400 ml-0.5 animate-pulse align-text-bottom"
      ></span>

      <div
        class="absolute -top-2 right-0 opacity-0 group-hover:opacity-100 transition-opacity flex gap-1"
      >
        <button
          v-if="!isUser"
          class="px-2 py-0.5 text-xs bg-gray-700 hover:bg-gray-600 text-gray-300 rounded"
          @click="copyContent"
        >
          复制
        </button>
        <button
          v-if="!isUser"
          class="px-2 py-0.5 text-xs bg-gray-700 hover:bg-gray-600 text-gray-300 rounded"
          @click="$emit('regenerate')"
        >
          重新生成
        </button>
      </div>

      <div
        v-if="message.created_at"
        class="text-[10px] text-gray-500 mt-1 opacity-0 group-hover:opacity-100 transition-opacity"
        :title="fullTime"
      >
        {{ relativeTime }}
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import type { Message } from '@ai-design/shared';
import MarkdownRenderer from '@ai-design/shared/components/MarkdownRenderer.vue';
import { useChatStore } from '@/stores/chatStore';

const props = defineProps<{
  message: Message;
  isStreaming?: boolean;
}>();

defineEmits<{
  regenerate: [];
}>();

const chatStore = useChatStore();

const reasoningExpanded = ref(true);

const isUser = computed(() => props.message.role === 'user');

// 思考内容来源：流式时来自 store，完成后来自 message 对象
const reasoningContent = computed(() => {
  if (props.isStreaming) {
    return chatStore.reasoningContent;
  }
  return props.message.reasoning_content || '';
});

const hasReasoning = computed(() => {
  return !!reasoningContent.value || (props.isStreaming && chatStore.isReasoning);
});

const formattedDuration = computed(() => {
  const ms = props.isStreaming
    ? chatStore.reasoningStartTime ? Date.now() - chatStore.reasoningStartTime : 0
    : props.message.reasoning_duration_ms || 0;
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
});

// 流式进行中自动展开，完成后 2 秒自动折叠
let autoCollapseTimer: ReturnType<typeof setTimeout> | null = null;
watch(
  () => props.isStreaming,
  (streaming) => {
    if (streaming) {
      reasoningExpanded.value = true;
      if (autoCollapseTimer) {
        clearTimeout(autoCollapseTimer);
        autoCollapseTimer = null;
      }
    } else if (hasReasoning.value) {
      reasoningExpanded.value = true;
      autoCollapseTimer = setTimeout(() => {
        reasoningExpanded.value = false;
      }, 2000);
    }
  }
);

const fullTime = computed(() => new Date(props.message.created_at).toLocaleString('zh-CN'));

const relativeTime = computed(() => {
  const diff = Date.now() - new Date(props.message.created_at).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return '刚刚';
  if (mins < 60) return `${mins}分钟前`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}小时前`;
  return new Date(props.message.created_at).toLocaleDateString('zh-CN');
});

async function copyContent() {
  try {
    await navigator.clipboard.writeText(props.message.content);
  } catch {
    // ignore
  }
}
</script>
