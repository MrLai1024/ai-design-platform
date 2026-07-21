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

function scrollToBottom(): void {
  if (containerRef.value) {
    containerRef.value.scrollTop = containerRef.value.scrollHeight
  }
}

// Auto-scroll to bottom whenever content changes (streaming or not)
watch(() => props.content, async () => {
  await nextTick()
  scrollToBottom()
})
</script>

<template>
  <div
    ref="containerRef"
    class="stream-document overflow-y-auto p-4"
    style="height: 0; flex: 1 1 0%;"
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
