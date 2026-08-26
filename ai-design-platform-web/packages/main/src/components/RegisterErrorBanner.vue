<template>
  <div
    class="fixed bottom-6 right-6 z-[60] max-w-sm rounded-lg border border-red-500/40 bg-slate-900/95 backdrop-blur px-4 py-3 shadow-[0_8px_40px_rgba(0,0,0,0.5)]"
    data-testid="register-error-banner"
    role="alert"
  >
    <div class="flex items-start gap-3">
      <p class="flex-1 text-sm text-red-400 leading-relaxed">
        {{ message }}
      </p>
      <button
        type="button"
        data-testid="banner-retry"
        class="text-xs text-cyan-400 hover:text-cyan-300 whitespace-nowrap"
        @click="$emit('retry')"
      >
        重试
      </button>
      <button
        type="button"
        data-testid="banner-close"
        class="text-slate-500 hover:text-slate-300"
        aria-label="关闭"
        @click="$emit('close')"
      >
        ✕
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  message: string;
}>();

defineEmits(['retry', 'close']);
</script>
