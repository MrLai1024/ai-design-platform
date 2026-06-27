<template>
  <div class="border-t border-gray-800 p-4 bg-gray-900">
    <div class="flex items-end gap-3 max-w-4xl mx-auto">
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
}>();

const emit = defineEmits<{
  'update:modelValue': [value: string];
  send: [content: string];
  stop: [];
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
