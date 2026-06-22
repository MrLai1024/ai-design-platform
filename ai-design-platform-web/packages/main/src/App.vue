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
            to="/ai-chat"
            class="h-full flex items-center px-5 text-sm text-slate-400 hover:text-cyan-300 hover:bg-slate-800/50 transition-all duration-300 border-b-2 border-transparent"
            active-class="text-cyan-400 bg-slate-800 border-cyan-400 font-semibold shadow-[inset_0_-2px_8px_rgba(6,182,212,0.15)]"
          >
            AI 对话
          </router-link>
          <router-link
            to="/ai-generation"
            class="h-full flex items-center px-5 text-sm text-slate-400 hover:text-cyan-300 hover:bg-slate-800/50 transition-all duration-300 border-b-2 border-transparent"
            active-class="text-cyan-400 bg-slate-800 border-cyan-400 font-semibold shadow-[inset_0_-2px_8px_rgba(6,182,212,0.15)]"
          >
            AI 生成
          </router-link>
          <router-link
            to="/ai-workflow"
            class="h-full flex items-center px-5 text-sm text-slate-400 hover:text-cyan-300 hover:bg-slate-800/50 transition-all duration-300 border-b-2 border-transparent"
            active-class="text-cyan-400 bg-slate-800 border-cyan-400 font-semibold shadow-[inset_0_-2px_8px_rgba(6,182,212,0.15)]"
          >
            AI 工作流
          </router-link>
        </nav>
      </div>
    </header>

    <!-- Page Content -->
    <router-view />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { useRoute } from 'vue-router';

const route = useRoute();

const showNavbar = computed(() => {
  return route.path !== '/' && route.path !== '';
});
</script>
