<!-- src/components/PreviewFrame.vue -->
<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted } from 'vue'
import { useGenerationStore } from '@/stores/generation'
import { useMultiCompiler } from '@/composables/useMultiCompiler'
import { generateHmrRuntimeScript } from '@/utils/hmrRuntime'
import { buildPreviewHtml } from '@/utils/buildPreviewHtml'
import { useComponentDocs } from '@/composables/useComponentDocs'

const store = useGenerationStore()
const { getConfig } = useComponentDocs()
const { isCompiling } = useMultiCompiler()
const iframeRef = ref<HTMLIFrameElement | null>(null)
const iframeReady = ref(false)
const hmrReady = ref(false)
const errorMessage = ref<string | null>(null)

const hmrRuntime = generateHmrRuntimeScript()

function buildHmrPreviewHtml(): string {
  const cdnUrls = getConfig().cdnUrls
  const cdnTags = cdnUrls.map((url: string) => {
    if (url.endsWith('.css')) return `<link rel="stylesheet" href="${url}">`
    return `<script src="${url}"><\/script>`
  }).join('\n')

  return `<!DOCTYPE html>
<html><head><meta charset="utf-8">
${cdnTags}
<style>body { margin: 0; padding: 16px; font-family: -apple-system, sans-serif; }</style>
</head><body>
<div id="app"></div>
${hmrRuntime}
</body></html>`
}

function initIframe(): void {
  if (!iframeRef.value) return
  iframeRef.value.srcdoc = buildHmrPreviewHtml()
  iframeReady.value = false
  hmrReady.value = false
}

/** Full page render via srcdoc — used when compilation produces complete output */
function renderFullPage(code: string, css: string): void {
  if (!iframeRef.value) return
  const cdnUrls = getConfig().cdnUrls
  const html = buildPreviewHtml(code, css, cdnUrls)
  iframeRef.value.srcdoc = html
  iframeReady.value = false
  hmrReady.value = false
  errorMessage.value = null
}

function sendHmrChunk(path: string, code: string, isLast: boolean): void {
  if (!iframeRef.value?.contentWindow || !hmrReady.value) return
  iframeRef.value.contentWindow.postMessage({
    type: 'hmr-file-chunk',
    path,
    code,
    isLast,
  }, '*')
}

function handleMessage(e: MessageEvent): void {
  if (e.source !== iframeRef.value?.contentWindow) return

  if (e.data?.type === 'ready') {
    iframeReady.value = true
    errorMessage.value = null
  }
  if (e.data?.type === 'hmr-ready') {
    hmrReady.value = true
  }
  if (e.data?.type === 'hmr-result') {
    if (e.data.type2 === 'compile-error' || e.data.type === 'compile-error') {
      errorMessage.value = `[${e.data.file}] ${e.data.error}`
    } else {
      errorMessage.value = null
    }
  }
  if (e.data?.type === 'err') {
    errorMessage.value = e.data.message as string
  }
}

// Watch compiled output: always do full page render (srcdoc)
// This is the primary rendering path. HMR is an enhancement for subsequent updates.
watch(
  () => store.compiledOutput,
  (output) => {
    if (!output || !iframeRef.value) return
    let code = output
    let css = ''
    const cssMatch = output.match(/__CSS__\s*=\s*["']([^"']*)["']/)
    if (cssMatch) {
      css = cssMatch[1] || ''
      code = output.replace(/\/\/ CSS\n__CSS__.*$/, '')
    }
    renderFullPage(code, css)
  },
)

// Watch generated files for incremental HMR updates (enhancement)
watch(
  () => store.generatedFiles,
  (newFiles, oldFiles) => {
    if (!hmrReady.value) return
    for (const [path, content] of Object.entries(newFiles)) {
      const oldContent = (oldFiles as Record<string, string>)?.[path] || ''
      if (content !== oldContent && content) {
        sendHmrChunk(path, content, true)
      }
    }
  },
  { deep: true },
)

onMounted(() => {
  window.addEventListener('message', handleMessage)
  initIframe()
})

onUnmounted(() => {
  window.removeEventListener('message', handleMessage)
})

function refresh(): void {
  if (store.compiledOutput) {
    let code = store.compiledOutput
    let css = ''
    const cssMatch = store.compiledOutput.match(/__CSS__\s*=\s*["']([^"]*)["']/)
    if (cssMatch) {
      css = cssMatch[1] || ''
      code = store.compiledOutput.replace(/\/\/ CSS\n__CSS__.*$/, '')
    }
    renderFullPage(code, css)
  } else {
    initIframe()
  }
}
</script>

<template>
  <div class="preview-frame flex flex-col h-full bg-white">
    <div class="px-4 py-2 border-b border-gray-200 bg-gray-50 flex items-center justify-between">
      <h2 class="text-sm font-semibold text-gray-700">实时预览</h2>
      <div class="flex items-center gap-2">
        <span v-if="isCompiling" class="text-xs px-2 py-0.5 rounded-full bg-yellow-100 text-yellow-700">
          编译中...
        </span>
        <span v-else-if="hmrReady" class="text-xs px-2 py-0.5 rounded-full bg-green-100 text-green-700">
          HMR 就绪
        </span>
        <span v-else-if="iframeReady" class="text-xs px-2 py-0.5 rounded-full bg-green-100 text-green-700">
          已就绪
        </span>
        <span v-else class="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-500">
          等待中
        </span>
        <button
          @click="refresh"
          class="text-xs text-blue-600 hover:text-blue-800 px-2 py-0.5 rounded hover:bg-blue-50 transition-colors"
          title="刷新预览"
        >
          ↻ 刷新
        </button>
      </div>
    </div>

    <div class="flex-1 relative">
      <div v-if="!iframeReady && !hmrReady" class="absolute inset-0 flex items-center justify-center text-gray-400 text-sm">
        <div class="text-center">
          <div v-if="isCompiling" class="animate-pulse">编译中...</div>
          <div v-else>输入描述开始生成组件</div>
        </div>
      </div>
      <iframe
        ref="iframeRef"
        sandbox="allow-scripts"
        class="w-full h-full border-none"
        title="组件预览"
      />
    </div>

    <div
      v-if="errorMessage"
      class="px-4 py-3 bg-red-50 border-t border-red-200"
    >
      <pre class="text-xs text-red-600 whitespace-pre-wrap font-mono">{{ errorMessage }}</pre>
    </div>
  </div>
</template>
