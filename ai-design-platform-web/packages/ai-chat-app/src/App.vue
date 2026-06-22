<template>
  <div class="ai-chat-app p-6">
    <h1 class="text-2xl font-bold text-gray-800 mb-4">AI 对话</h1>
    <nav class="flex space-x-4 mb-6">
      <router-link to="/" class="text-blue-600 hover:underline"> 首页 </router-link>
      <router-link to="/about" class="text-blue-600 hover:underline"> 关于 </router-link>
    </nav>
    <router-view />
  </div>
</template>

<script setup lang="ts">
import { onGlobalStateChange } from '@ai-design/micro-core';

onGlobalStateChange((state, prev) => {
  console.log('[ai-chat-app] global state changed:', state, prev);
});
</script>
