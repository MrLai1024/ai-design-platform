<template>
  <div id="main-app" class="min-h-screen bg-gray-50">
    <!-- Top Navigation Bar — only shown in sub-app routes -->
    <header
      v-if="showNavbar"
      class="sticky top-0 z-50 bg-slate-900/80 backdrop-blur-md border-b border-cyan-500/30 shadow-[0_2px_24px_rgba(6,182,212,0.1)]"
    >
      <div class="flex items-center h-14 px-6">
        <nav class="flex items-center h-full">
          <router-link
            to="/"
            class="h-full flex items-center px-5 text-sm text-slate-400 hover:text-cyan-300 hover:bg-slate-800/50 transition-all duration-300 border-b-2 border-transparent"
            active-class="text-cyan-400 bg-slate-800 border-cyan-400 font-semibold shadow-[inset_0_-2px_8px_rgba(6,182,212,0.15)]"
          >
            首页
          </router-link>
          <router-link
            to="/ai-generation"
            class="h-full flex items-center px-5 text-sm text-slate-400 hover:text-cyan-300 hover:bg-slate-800/50 transition-all duration-300 border-b-2 border-transparent"
            active-class="text-cyan-400 bg-slate-800 border-cyan-400 font-semibold shadow-[inset_0_-2px_8px_rgba(6,182,212,0.15)]"
          >
            AI 生成
          </router-link>
          <router-link
            to="/project-space"
            class="h-full flex items-center px-5 text-sm text-slate-400 hover:text-cyan-300 hover:bg-slate-800/50 transition-all duration-300 border-b-2 border-transparent"
            active-class="text-cyan-400 bg-slate-800 border-cyan-400 font-semibold shadow-[inset_0_-2px_8px_rgba(6,182,212,0.15)]"
          >
            项目空间
          </router-link>
        </nav>
        <!-- Personal info entry — after all nav menu items, pinned to the far right -->
        <AccountEntry :account="accountState.account" :password="accountState.password" />
      </div>
    </header>

    <!-- Auto-register failure notice — dismissible, never blocks the platform -->
    <RegisterErrorBanner
      v-if="accountState.status === 'error'"
      :message="accountState.error ?? ''"
      @close="dismissError()"
      @retry="init()"
    />

    <!-- Page Content -->
    <router-view />

    <!--
      Pre-render all sub-app containers so qiankun's sandbox can find them
      during module initialization. Use v-show (not v-if) so they remain in
      the DOM — qiankun needs them before activation. Only the active one
      is visible; others are display:none.
    -->
    <div id="sub-app-generation" v-show="isRoute('/ai-generation')" class="sub-app-container" />
    <div id="sub-app-project-space" v-show="isRoute('/project-space')" class="sub-app-container" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted } from 'vue';
import { useRoute } from 'vue-router';
import { GLOBAL_EVENTS } from '@ai-design/shared';
import AccountEntry from './components/AccountEntry.vue';
import RegisterErrorBanner from './components/RegisterErrorBanner.vue';
import { useAccount } from './composables/useAccount';

const route = useRoute();

function isRoute(path: string): boolean {
  return route.path.startsWith(path);
}

const showNavbar = computed(() => route.path !== '/' && route.path !== '');

// First visit → auto-register and persist credentials; existing credentials are
// reused as-is. Runs async and never blocks the app on failure (see banner).
const { state: accountState, init, dismissError, refreshCredentials } = useAccount();

// A 401 anywhere in the platform wipes the stored credentials and fires
// AUTH_UNAUTHORIZED → reset the account state and re-register so the session
// recovers in place instead of requiring a manual refresh.
function handleAuthUnauthorized(): void {
  void refreshCredentials();
}

onMounted(() => {
  window.addEventListener(GLOBAL_EVENTS.AUTH_UNAUTHORIZED, handleAuthUnauthorized);
  void init();
});

onUnmounted(() => {
  window.removeEventListener(GLOBAL_EVENTS.AUTH_UNAUTHORIZED, handleAuthUnauthorized);
});
</script>

<style>
.sub-app-container {
  height: calc(100vh - 56px);
}
</style>
