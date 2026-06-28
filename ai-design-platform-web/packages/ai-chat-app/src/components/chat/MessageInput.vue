<template>
  <div class="border-t border-gray-800 p-4 bg-gray-900">
    <div class="flex items-end gap-3 max-w-4xl mx-auto">
      <!-- 深度思考切换 -->
      <button
        :title="enableThinking ? '深度思考已开启' : '深度思考已关闭'"
        class="flex-shrink-0 w-10 h-10 rounded-lg border transition-colors flex items-center justify-center"
        :class="enableThinking
          ? 'bg-indigo-900/40 border-indigo-500 text-indigo-300 hover:bg-indigo-900/60'
          : 'bg-gray-800 border-gray-700 text-gray-500 hover:border-gray-600 hover:text-gray-400'"
        @click="$emit('toggleThinking')"
      >
        <svg xmlns="http://www.w3.org/2000/svg" class="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
          <path d="M12 4a3 3 0 0 0-3-3 3 3 0 0 0-3 3c0 .7.2 1.3.6 1.8C5.2 6.8 4 8.7 4 11c0 1.5.5 2.9 1.3 4 .2.3.4.5.4.9 0 .9-.4 1.7-1 2.3A2 2 0 0 0 6 21c1 0 1.9-.5 2.4-1.2.3-.4.7-.7 1.2-.7h4.8c.5 0 .9.3 1.2.7.5.7 1.4 1.2 2.4 1.2a2 2 0 0 0 1.3-3.3c-.6-.6-1-1.4-1-2.3 0-.4.2-.6.4-.9.8-1.1 1.3-2.5 1.3-4 0-2.3-1.2-4.2-2.6-5.2.4-.5.6-1.1.6-1.8 0-1.7-1.3-3-3-3a3 3 0 0 0-3 3" />
          <path d="M12 4v17" />
          <path d="M9 9h.01" />
          <path d="M15 9h.01" />
        </svg>
      </button>

      <textarea
        ref="textareaRef"
        v-model="localInput"
        :disabled="isStreaming && !canStop"
        :rows="rows"
        class="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-4 py-3 text-sm text-gray-200 placeholder-gray-500 resize-none focus:outline-none focus:border-indigo-500 transition-colors disabled:opacity-50"
        placeholder="输入消息... (Enter 发送, Shift+Enter 换行)"
        @keydown="onKeydown"
        @input="autoResize"
      />
      <button
        v-if="isStreaming && canStop"
        class="px-5 py-3 bg-red-600 hover:bg-red-500 text-white text-sm font-medium rounded-lg transition-colors flex-shrink-0"
        @click="$emit('stop')"
      >
        ⏹ 停止
      </button>
      <button
        v-else
        :disabled="!canSend"
        class="px-5 py-3 bg-indigo-600 hover:bg-indigo-500 disabled:bg-gray-700 disabled:text-gray-500 text-white text-sm font-medium rounded-lg transition-colors flex-shrink-0"
        @click="send"
      >
        发送
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue';

const props = defineProps<{
  modelValue: string;
  isStreaming: boolean;
  enableThinking: boolean;
}>();

const emit = defineEmits<{
  'update:modelValue': [value: string];
  send: [content: string];
  stop: [];
  toggleThinking: [];
}>();

const textareaRef = ref<HTMLTextAreaElement | null>(null);
const rows = ref(1);

const localInput = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
});

const canSend = computed(() => localInput.value.trim().length > 0 && !props.isStreaming);
const canStop = computed(() => props.isStreaming);

function autoResize() {
  const el = textareaRef.value;
  if (!el) return;
  el.style.height = 'auto';
  const lineHeight = 24;
  const maxRows = 6;
  const newRows = Math.min(Math.ceil(el.scrollHeight / lineHeight), maxRows);
  rows.value = newRows;
  el.style.height = newRows * lineHeight + 'px';
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    send();
  }
}

function send() {
  if (!canSend.value) return;
  emit('send', localInput.value.trim());
}

watch(
  () => props.isStreaming,
  (v) => {
    if (!v) {
      textareaRef.value?.focus();
    }
  },
);
</script>
