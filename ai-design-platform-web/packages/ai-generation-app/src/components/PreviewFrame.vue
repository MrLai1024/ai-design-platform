<!-- src/components/PreviewFrame.vue -->
<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted } from 'vue'
import { useGenerationStore } from '@/stores/generation'
import { useMultiCompiler } from '@/composables/useMultiCompiler'
import { initBundler, preloadBundler, bundleProject, getBundlerStatus, type BundleResult } from '@/bundler/useBundler'
import { buildPreviewDoc } from '@/bundler/previewTemplate'
import { buildPreviewHtml } from '@/utils/buildPreviewHtml'
import { useComponentDocs } from '@/composables/useComponentDocs'

const store = useGenerationStore()
const { getConfig } = useComponentDocs()
const { isCompiling } = useMultiCompiler()

const iframeRef = ref<HTMLIFrameElement | null>(null)
const iframeReady = ref(false)
const bundlerFailed = ref(false)
const bundlerInitializing = ref(false)
const building = ref(false)
const errorMessage = ref<string | null>(null)

let debounceTimer: ReturnType<typeof setTimeout> | null = null
let buildGen = 0
const DEBOUNCE_MS = 400

// ── 主路径：esbuild-wasm 完整工程打包 ──

function renderDoc(js: string, css: string): void {
  if (!iframeRef.value) return
  iframeRef.value.srcdoc = buildPreviewDoc({ js, css, cdnUrls: getConfig().cdnUrls })
  iframeReady.value = false
  errorMessage.value = null
}

async function reportErrors(result: BundleResult): Promise<void> {
  // AgentLog 编译卡片 —— 前端 esbuild 预览错误是辅助信号（node-compiler 是
  // 编译通过判据），标注来源以便区分
  store.addAgentLogEntry({
    id: Date.now().toString(36) + Math.random().toString(36).slice(2, 7),
    type: 'compile',
    timestamp: Date.now(),
    compileOk: false,
    compileErrors: result.errors.map((e) => ({ file: e.file, line: e.line, message: e.text, source: 'preview' as const })),
  })
  // 上报后端（生成阶段才有 generation_id）
  if (store.currentGenerationId) {
    try {
      await fetch('/api/v1/generation/compile_feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          generation_id: store.currentGenerationId,
          ok: false,
          errors: result.errors,
        }),
      })
    } catch {
      /* 上报失败不影响预览 */
    }
  }
}

async function doBundle(): Promise<void> {
  const gen = ++buildGen
  const files = { ...store.generatedFiles }
  if (Object.keys(files).length === 0) return

  building.value = true
  try {
    const result = await bundleProject(files)
    if (gen !== buildGen) return // 过期构建，丢弃

    if (result.ok && result.js) {
      renderDoc(result.js, result.css || '')
      // 之前失败过 → 绿色恢复卡片 + 上报成功（清除后端 pending errors）
      if (errorMessage.value) {
        store.addAgentLogEntry({
          id: Date.now().toString(36) + Math.random().toString(36).slice(2, 7),
          type: 'compile',
          timestamp: Date.now(),
          compileOk: true,
        })
        if (store.currentGenerationId) {
          fetch('/api/v1/generation/compile_feedback', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ generation_id: store.currentGenerationId, ok: true, errors: [] }),
          }).catch(() => { /* 上报失败不影响预览 */ })
        }
      }
      errorMessage.value = null
    } else if (result.partial) {
      // 流式中途依赖未齐 —— 静默，保持最近成功画面
    } else {
      errorMessage.value = result.errors
        .map((e) => `${e.file}:${e.line} — ${e.text}`)
        .join('\n')
      await reportErrors(result)
    }
  } catch (e: any) {
    // wasm 初始化失败等 → 降级
    if (gen === buildGen) activateFallback()
  } finally {
    if (gen === buildGen) building.value = false
  }
}

function scheduleBundle(): void {
  if (bundlerFailed.value) return
  if (debounceTimer) clearTimeout(debounceTimer)
  debounceTimer = setTimeout(() => doBundle(), DEBOUNCE_MS)
}

// ── 降级路径：原单组件 compileSFC 预览 ──

function activateFallback(): void {
  bundlerFailed.value = true
}

function renderLegacy(output: string): void {
  if (!iframeRef.value || !output) return
  let code = output
  let css = ''
  const cssMatch = output.match(/__CSS__\s*=\s*["']([^"']*)["']/)
  if (cssMatch) {
    css = cssMatch[1] || ''
    code = output.replace(/\/\/ CSS\n__CSS__.*$/, '')
  }
  iframeRef.value.srcdoc = buildPreviewHtml(code, css, getConfig().cdnUrls)
  iframeReady.value = false
}

watch(
  () => store.generatedFiles,
  () => scheduleBundle(),
  { deep: true },
)

// 降级路径：监听 compiledOutput
watch(
  () => store.compiledOutput,
  (output) => {
    if (bundlerFailed.value && output) renderLegacy(output)
  },
)

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

onMounted(async () => {
  window.addEventListener('message', handleMessage)
  preloadBundler()
  bundlerInitializing.value = getBundlerStatus() !== 'ready'
  try {
    await initBundler()
  } catch {
    activateFallback()
  } finally {
    bundlerInitializing.value = false
  }
})

onUnmounted(() => {
  window.removeEventListener('message', handleMessage)
  if (debounceTimer) clearTimeout(debounceTimer)
})

function refresh(): void {
  if (bundlerFailed.value) {
    if (store.compiledOutput) renderLegacy(store.compiledOutput)
  } else {
    doBundle()
  }
}
</script>

<template>
  <div class="preview-frame flex flex-col h-full bg-white">
    <div class="px-4 py-2 border-b border-gray-200 bg-gray-50 flex items-center justify-between">
      <h2 class="text-sm font-semibold text-gray-700">实时预览</h2>
      <div class="flex items-center gap-2">
        <span v-if="bundlerFailed" class="text-xs px-2 py-0.5 rounded-full bg-orange-100 text-orange-700">
          降级预览
        </span>
        <span v-else-if="bundlerInitializing" class="text-xs px-2 py-0.5 rounded-full bg-blue-100 text-blue-700">
          编译器初始化中...
        </span>
        <span v-else-if="building || isCompiling" class="text-xs px-2 py-0.5 rounded-full bg-yellow-100 text-yellow-700">
          打包中...
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
      <div v-if="!iframeReady" class="absolute inset-0 flex items-center justify-center text-gray-400 text-sm pointer-events-none">
        <div class="text-center">
          <div v-if="building || isCompiling" class="animate-pulse">打包中...</div>
          <div v-else-if="Object.keys(store.generatedFiles).length === 0">输入描述开始生成组件</div>
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
      class="px-4 py-3 bg-red-50 border-t border-red-200 max-h-[200px] overflow-y-auto"
    >
      <pre class="text-xs text-red-600 whitespace-pre-wrap font-mono">{{ errorMessage }}</pre>
    </div>
  </div>
</template>
