<!-- src/components/StreamDocument.vue -->
<script setup lang="ts">
import { ref, watch, computed, nextTick } from 'vue'
import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js'
import DOMPurify from 'dompurify'

const props = withDefaults(defineProps<{
  content: string
  isStreaming?: boolean
  language?: 'md' | 'html'
}>(), {
  content: '',
  isStreaming: false,
  language: 'md',
})

const containerRef = ref<HTMLElement | null>(null)

const md = new MarkdownIt({
  html: false,
  linkify: true,
  typographer: true,
  highlight(str: string, lang: string): string {
    if (lang && hljs.getLanguage(lang)) {
      try {
        return hljs.highlight(str, { language: lang }).value
      } catch {
        /* fallthrough */
      }
    }
    return ''
  },
})

const renderedContent = computed(() => {
  if (props.language === 'html') {
    return DOMPurify.sanitize(props.content)
  }
  return DOMPurify.sanitize(md.render(props.content))
})

// Auto-scroll when streaming
watch(
  () => props.content,
  async () => {
    if (!props.isStreaming) return
    await nextTick()
    if (containerRef.value) {
      containerRef.value.scrollTop = containerRef.value.scrollHeight
    }
  },
)
</script>

<template>
  <div
    ref="containerRef"
    class="stream-document flex-1 overflow-auto p-4"
  >
    <div
      v-if="language === 'html'"
      class="prose prose-sm max-w-none"
      v-html="renderedContent"
    />
    <div
      v-else
      class="prose prose-sm max-w-none markdown-body"
      v-html="renderedContent"
    />
    <div
      v-if="isStreaming && !content"
      class="text-gray-400 text-sm text-center mt-8"
    >
      等待生成...
    </div>
  </div>
</template>

<style scoped>
.stream-document {
  scroll-behavior: smooth;
}
</style>
