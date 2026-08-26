<template>
  <div class="ml-auto h-full flex items-center" data-testid="account-entry-wrap">
    <button
      type="button"
      data-testid="account-entry"
      class="h-10 px-3 mx-2 rounded-lg flex items-center gap-2 text-sm text-slate-300 hover:text-cyan-300 hover:bg-slate-800/50 transition-all duration-300"
      @click="open = true"
    >
      <span
        class="w-7 h-7 rounded-full bg-cyan-500/20 border border-cyan-500/40 flex items-center justify-center text-xs font-semibold text-cyan-300"
      >
        {{ account ? account.charAt(0).toUpperCase() : '👤' }}
      </span>
      <span v-if="account" data-testid="account-name">{{ account }}</span>
    </button>

    <Teleport to="body">
      <div
        v-if="open"
        class="fixed inset-0 z-[60] flex items-center justify-center"
        data-testid="account-modal-wrap"
      >
        <div
          class="absolute inset-0 bg-slate-950/60 backdrop-blur-sm"
          data-testid="account-modal-backdrop"
          @click="open = false"
        />
        <div
          class="relative w-80 rounded-xl border border-slate-700/60 bg-slate-900 shadow-[0_8px_40px_rgba(0,0,0,0.5)]"
          data-testid="account-modal"
        >
          <div class="flex items-center justify-between px-5 py-4 border-b border-slate-800">
            <h3 class="text-sm font-semibold text-slate-200">个人信息</h3>
            <button
              type="button"
              data-testid="account-modal-close"
              class="text-slate-500 hover:text-slate-300 transition-colors"
              aria-label="关闭"
              @click="open = false"
            >
              ✕
            </button>
          </div>
          <div class="px-5 py-4 space-y-3">
            <div class="flex items-center justify-between">
              <span class="text-xs text-slate-500">账号</span>
              <span class="text-sm text-slate-200 font-mono">{{ account ?? '—' }}</span>
            </div>
            <div class="flex items-center justify-between">
              <span class="text-xs text-slate-500">密码</span>
              <span class="text-sm text-slate-200 font-mono">{{ password ?? '—' }}</span>
            </div>
            <p class="text-xs text-slate-600 leading-relaxed pt-1 border-t border-slate-800">
              账号信息保存在本浏览器,清除缓存后将自动分配新账号
            </p>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue';

defineProps<{
  account: string | null;
  password: string | null;
}>();

const open = ref(false);
</script>
