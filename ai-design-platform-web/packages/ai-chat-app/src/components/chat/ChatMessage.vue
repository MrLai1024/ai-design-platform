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
      <MarkdownRenderer v-if="!isUser" :content="message.content" />
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
import { computed } from 'vue';
import type { Message } from '@ai-design/shared';
import MarkdownRenderer from '@ai-design/shared/components/MarkdownRenderer.vue';

const props = defineProps<{
  message: Message;
  isStreaming?: boolean;
}>();

defineEmits<{
  regenerate: [];
}>();

const isUser = computed(() => props.message.role === 'user');

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
