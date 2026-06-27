<template>
  <div class="markdown-renderer prose prose-sm max-w-none" v-html="renderedHtml" />
</template>

<script setup lang="ts">
import { toRef, type Ref } from 'vue';
import { useMarkdown } from '../composables/useMarkdown';

const props = defineProps<{
  content: string;
}>();

const input = toRef(props, 'content') as Ref<string>;
const { renderedHtml } = useMarkdown(input);
</script>

<style>
/* 代码块容器样式（覆盖 Tailwind Typography 默认） */
.markdown-renderer pre {
  position: relative;
  background: #1e1e2e;
  border-radius: 0.5rem;
  padding: 1rem;
  overflow-x: auto;
}

.markdown-renderer pre code {
  background: transparent;
  font-size: 0.875rem;
  line-height: 1.5;
}

.markdown-renderer code {
  background: #2d2d3f;
  padding: 0.125rem 0.375rem;
  border-radius: 0.25rem;
  font-size: 0.875em;
}

.markdown-renderer pre code {
  padding: 0;
  background: transparent;
}
</style>
