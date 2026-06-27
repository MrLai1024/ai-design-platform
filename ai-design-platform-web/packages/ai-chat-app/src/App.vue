<template>
  <div class="ai-chat-app h-screen">
    <router-view />
  </div>
</template>

<script setup lang="ts">
import { onGlobalStateChange } from '@ai-design/micro-core';

onGlobalStateChange((state, prev) => {
  console.log('[ai-chat-app] global state changed:', state, prev);
});
</script>
