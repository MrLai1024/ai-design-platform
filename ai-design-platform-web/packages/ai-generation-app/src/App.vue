<template>
  <div class="ai-generation-app">
    <router-view />
  </div>
</template>

<script setup lang="ts">
import { onGlobalStateChange } from '@ai-design/micro-core';
onGlobalStateChange((state, prev) => {
  console.log('[ai-generation-app] global state changed:', state, prev);
});
</script>

<style>
/* reset 防基座样式污染 */
.ai-generation-app {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}
.ai-generation-app *,
.ai-generation-app *::before,
.ai-generation-app *::after {
  box-sizing: border-box;
}
</style>

