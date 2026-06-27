// src/composables/usePreviewRenderer.ts
import { ref, watch, onMounted, onUnmounted } from 'vue'
import { useGenerationStore } from '@/stores/generation'
import { scanCode } from '@/utils/securityScan'
import { buildPreviewHtml } from '@/utils/buildPreviewHtml'
import { useComponentDocs } from './useComponentDocs'

export function usePreviewRenderer() {
  const store = useGenerationStore()
  const { getConfig } = useComponentDocs()
  const iframeRef = ref<HTMLIFrameElement | null>(null)
  const iframeReady = ref(false)
  const errorMessage = ref<string | null>(null)

  function sendToFrame(compiledCode: string, compiledCSS: string): void {
    if (!iframeRef.value) return
    const cdnUrls = getConfig().cdnUrls
    const html = buildPreviewHtml(compiledCode, compiledCSS, cdnUrls)
    iframeRef.value.srcdoc = html
    iframeReady.value = false
  }

  function handleMessage(e: MessageEvent): void {
    if (e.source !== iframeRef.value?.contentWindow) return
    if (e.data?.type === 'ready') {
      iframeReady.value = true
      errorMessage.value = null
    }
    if (e.data?.type === 'err') {
      errorMessage.value = e.data.message as string
    }
  }

  // 监听编译输出变化
  watch(
    () => store.compiledOutput,
    (output) => {
      if (!output) return
      // 安全扫描
      const scanErr = scanCode(output)
      if (scanErr) {
        errorMessage.value = scanErr
        return
      }
      // 提取 CSS
      let code = output
      let css = ''
      const cssMatch = output.match(/__CSS__\s*=\s*["']([^"']*)["']/)
      if (cssMatch) {
        css = cssMatch[1] || ''
        code = output.replace(/\/\/ CSS\n__CSS__.*$/, '')
      }
      sendToFrame(code, css)
    },
  )

  onMounted(() => {
    window.addEventListener('message', handleMessage)
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
      sendToFrame(code, css)
    }
  }

  return { iframeRef, iframeReady, errorMessage, refresh }
}
