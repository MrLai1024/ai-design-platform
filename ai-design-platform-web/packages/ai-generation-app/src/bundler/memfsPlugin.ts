// src/bundler/memfsPlugin.ts
// esbuild plugin: resolve imports from the in-memory generated file set.
import type { Plugin } from 'esbuild-wasm'

/** 裸模块标识符 → external（由 iframe import map 提供） */
const EXTERNALS = new Set(['vue', 'vue-router', 'pinia'])

const RESOLVE_EXTS = ['.vue', '.ts', '.js', '.css']

export interface MemfsPluginOptions {
  /** path (posix, no leading slash) -> file content */
  files: Map<string, string>
  /** collected CSS output — plugins append here */
  cssChunks: string[]
}

function normalizePath(p: string): string {
  const parts: string[] = []
  for (const seg of p.split('/')) {
    if (!seg || seg === '.') continue
    if (seg === '..') parts.pop()
    else parts.push(seg)
  }
  return parts.join('/')
}

function dirname(p: string): string {
  const idx = p.lastIndexOf('/')
  return idx === -1 ? '' : p.slice(0, idx)
}

export function createMemfsPlugin(opts: MemfsPluginOptions): Plugin {
  const { files, cssChunks } = opts

  function tryResolve(base: string): string | null {
    if (files.has(base)) return base
    for (const ext of RESOLVE_EXTS) {
      if (files.has(base + ext)) return base + ext
    }
    for (const ext of RESOLVE_EXTS) {
      const idx = `${base}/index${ext}`
      if (files.has(idx)) return idx
    }
    return null
  }

  return {
    name: 'memfs',
    setup(build) {
      // ── 裸模块 external ──
      build.onResolve({ filter: /^(vue|vue-router|pinia)(\/.*)?$/ }, (args) => ({
        path: args.path,
        external: true,
      }))

      // ── 别名 @/ → src/ ──
      build.onResolve({ filter: /^@\// }, (args) => {
        const resolved = tryResolve(normalizePath('src/' + args.path.slice(2)))
        return resolved
          ? { path: resolved, namespace: 'memfs' }
          : { errors: [{ text: `Could not resolve "${args.path}" (alias @/)`, notes: [] }] }
      })

      // ── 相对路径 ──
      build.onResolve({ filter: /^\.{1,2}\// }, (args) => {
        const importerDir = args.importer ? dirname(args.importer) : ''
        const resolved = tryResolve(normalizePath(importerDir ? `${importerDir}/${args.path}` : args.path))
        return resolved
          ? { path: resolved, namespace: 'memfs' }
          : { errors: [{ text: `Could not resolve "${args.path}" from "${args.importer}"`, notes: [] }] }
      })

      // ── 根路径 (/src/... 或 src/...) ──
      build.onResolve({ filter: /^\// }, (args) => {
        const resolved = tryResolve(normalizePath(args.path.slice(1)))
        return resolved
          ? { path: resolved, namespace: 'memfs' }
          : { errors: [{ text: `Could not resolve "${args.path}"`, notes: [] }] }
      })

      // ── 入口解析（catch-all，最后注册）──
      // entryPoints 是 "src/main.ts"（无 ./ 前缀），esbuild 的默认解析器在
      // wasm 下无法读目录（"not implemented on js"）→ 入口必须由 memfs 接管。
      // importer === '' 只出现在入口；其它导入已被上面的 filter 处理。
      build.onResolve({ filter: /.*/ }, (args) => {
        if (args.importer !== '') return null
        const resolved = tryResolve(normalizePath(args.path))
        return resolved
          ? { path: resolved, namespace: 'memfs' }
          : { errors: [{ text: `Could not resolve "${args.path}"`, notes: [] }] }
      })

      // ── 非 .vue 文件加载（.vue 由 vuePlugin 先注册接管）──
      build.onLoad({ filter: /\.css$/, namespace: 'memfs' }, (args) => {
        const content = files.get(args.path)
        if (content === undefined) {
          return { errors: [{ text: `File not found in memfs: ${args.path}`, notes: [] }] }
        }
        cssChunks.push(`/* ${args.path} */\n${content}`)
        return { contents: '', loader: 'js' }
      })

      build.onLoad({ filter: /\.ts$/, namespace: 'memfs' }, (args) => {
        const content = files.get(args.path)
        if (content === undefined) {
          return { errors: [{ text: `File not found in memfs: ${args.path}`, notes: [] }] }
        }
        return { contents: content, loader: 'ts' }
      })

      build.onLoad({ filter: /\.js$/, namespace: 'memfs' }, (args) => {
        const content = files.get(args.path)
        if (content === undefined) {
          return { errors: [{ text: `File not found in memfs: ${args.path}`, notes: [] }] }
        }
        return { contents: content, loader: 'js' }
      })

      // ── 合成入口 / 其他 JSON 等 ──
      build.onLoad({ filter: /__preview_entry__\.ts$/, namespace: 'memfs' }, () => ({
        contents: files.get('__preview_entry__.ts') ?? '',
        loader: 'ts',
      }))
    },
  }
}
