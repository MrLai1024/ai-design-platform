// src/bundler/useBundler.ts
// 浏览器内 esbuild-wasm 打包管线：初始化、增量重建、partial 错误分类、合成入口。
import * as esbuild from 'esbuild-wasm'
import wasmURL from 'esbuild-wasm/esbuild.wasm'
import { createMemfsPlugin } from './memfsPlugin'
import { createVuePlugin } from './vuePlugin'

export interface BundleError {
  file: string
  line: number
  column: number
  text: string
}

export interface BundleResult {
  ok: boolean
  /** 打包成功时的 ES module JS */
  js?: string
  /** 收集的全部 CSS（SFC style + .css 文件） */
  css?: string
  errors: BundleError[]
  /** true = 全部错误均为流式中途依赖未齐（Could not resolve），应静默等待 */
  partial: boolean
}

export type BundlerStatus = 'idle' | 'initializing' | 'ready' | 'failed'

let _status: BundlerStatus = 'idle'
let _initPromise: Promise<void> | null = null
let _ctx: esbuild.BuildContext | null = null

export function getBundlerStatus(): BundlerStatus {
  return _status
}

/** 初始化 esbuild-wasm（幂等）。失败时抛异常由调用方降级。 */
export async function initBundler(): Promise<void> {
  if (_status === 'ready') return
  if (_initPromise) return _initPromise

  _status = 'initializing'
  _initPromise = (async () => {
    try {
      await esbuild.initialize({ wasmURL, worker: true })
      _status = 'ready'
    } catch (e) {
      _status = 'failed'
      _initPromise = null
      throw e
    }
  })()
  return _initPromise
}

/** 空闲时预加载 wasm（不阻塞 UI） */
export function preloadBundler(): void {
  const cb = () => {
    initBundler().catch(() => {
      /* 降级路径由 PreviewFrame 在 build 时处理 */
    })
  }
  if (typeof requestIdleCallback === 'function') {
    requestIdleCallback(cb, { timeout: 5000 })
  } else {
    setTimeout(cb, 2000)
  }
}

const PARTIAL_RE = /Could not resolve/

function toBundleError(m: esbuild.Message): BundleError {
  return {
    file: m.location?.file ?? '',
    line: m.location?.line ?? 0,
    column: m.location?.column ?? 0,
    text: m.text,
  }
}

function isPartialErrors(errors: BundleError[]): boolean {
  return errors.length > 0 && errors.every((e) => PARTIAL_RE.test(e.text))
}

/** 规范化路径：去掉 ./ 前缀，统一 posix */
function normalizeInputPath(p: string): string {
  return p.replace(/^\.\//, '').replace(/\\/g, '/')
}

/** 为无 src/main.ts 的旧格式工程合成入口 */
function makeSyntheticEntry(files: Map<string, string>): void {
  const appPath = ['src/App.vue', 'App.vue'].find((p) => files.has(p))
  if (!appPath) return
  const importPath = appPath === 'App.vue' ? './App.vue' : './App.vue'
  files.set(
    '__preview_entry__.ts',
    [
      `import { createApp } from 'vue'`,
      `import App from '${importPath}'`,
      `const app = createApp(App)`,
      `app.mount('#app')`,
    ].join('\n'),
  )
}

function pickEntry(files: Map<string, string>): string | null {
  if (files.has('src/main.ts')) return 'src/main.ts'
  if (files.has('main.ts')) return 'main.ts'
  makeSyntheticEntry(files)
  if (files.has('__preview_entry__.ts')) return '__preview_entry__.ts'
  return null
}

/**
 * 打包生成的完整工程。
 * files: Record<path, content>（path 可带或不带 ./ 前缀，会规范化）
 */
export async function bundleProject(input: Record<string, string>): Promise<BundleResult> {
  if (_status !== 'ready') {
    await initBundler()
  }

  const files = new Map<string, string>()
  for (const [p, c] of Object.entries(input)) {
    if (c) files.set(normalizeInputPath(p), c)
  }

  const entry = pickEntry(files)
  if (!entry) {
    return {
      ok: false,
      errors: [{ file: '', line: 0, column: 0, text: 'No entry file (src/main.ts or App.vue) found' }],
      partial: false,
    }
  }

  const cssChunks: string[] = []

  // 使用增量 context：同一 files Map 引用，rebuild 时只重编变化部分
  const buildOptions: esbuild.BuildOptions = {
    entryPoints: [entry],
    bundle: true,
    write: false,
    format: 'esm',
    target: 'es2020',
    sourcemap: false,
    logLevel: 'silent',
    define: {
      'process.env.NODE_ENV': '"development"',
      __VUE_OPTIONS_API__: 'true',
      __VUE_PROD_DEVTOOLS__: 'false',
      __VUE_PROD_HYDRATION_MISMATCH_DETAILS__: 'false',
    },
    plugins: [createVuePlugin({ files, cssChunks }), createMemfsPlugin({ files, cssChunks })],
  }

  try {
    if (!_ctx) {
      _ctx = await esbuild.context(buildOptions)
    }
    const result = await _ctx.rebuild()

    const jsFile = result.outputFiles?.find((f) => f.path.endsWith('.js'))
    return {
      ok: true,
      js: jsFile?.text ?? '',
      css: cssChunks.join('\n'),
      errors: [],
      partial: false,
    }
  } catch (e: any) {
    const messages: esbuild.Message[] = e?.errors ?? [{ text: String(e?.message ?? e) }]
    const errors = messages.map(toBundleError)
    return {
      ok: false,
      css: cssChunks.join('\n'),
      errors,
      partial: isPartialErrors(errors),
    }
  }
}

/** 销毁增量 context（生成会话结束时调用） */
export async function disposeBundler(): Promise<void> {
  if (_ctx) {
    await _ctx.dispose()
    _ctx = null
  }
}
