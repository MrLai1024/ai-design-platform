// src/bundler/vuePlugin.ts
// esbuild plugin: compile .vue SFC files via vue/compiler-sfc inside the bundle graph.
import type { Plugin } from 'esbuild-wasm'
import { parse, compileScript, compileTemplate, compileStyle } from 'vue/compiler-sfc'

export interface VuePluginOptions {
  files: Map<string, string>
  cssChunks: string[]
}

function hash(str: string): string {
  let h = 0
  for (let i = 0; i < str.length; i++) {
    h = ((h << 5) - h + str.charCodeAt(i)) | 0
  }
  return Math.abs(h).toString(36).slice(0, 8)
}

export function createVuePlugin(opts: VuePluginOptions): Plugin {
  const { files, cssChunks } = opts

  return {
    name: 'memfs-vue',
    setup(build) {
      build.onLoad({ filter: /\.vue$/, namespace: 'memfs' }, (args) => {
        const source = files.get(args.path)
        if (source === undefined) {
          return { errors: [{ text: `File not found in memfs: ${args.path}`, notes: [] }] }
        }

        const id = hash(args.path)
        const { descriptor, errors } = parse(source, { filename: args.path })
        if (errors.length) {
          return {
            errors: errors.map((e) => ({
              text: typeof e === 'string' ? e : e.message,
              notes: [],
            })),
          }
        }

        const hasScoped = descriptor.styles.some((s) => s.scoped)
        const scopeId = hasScoped ? `data-v-${id}` : null

        // ── 样式：编译后收集，不进 bundle ──
        for (const style of descriptor.styles) {
          const result = compileStyle({
            source: style.content,
            filename: args.path,
            id,
            scoped: style.scoped,
          })
          if (result.code) cssChunks.push(`/* ${args.path} */\n${result.code}`)
        }

        let js: string

        if (descriptor.script || descriptor.scriptSetup) {
          // script / script setup — inlineTemplate 统一处理（script setup 与普通 script 均适用）
          const compiled = compileScript(descriptor, {
            id,
            inlineTemplate: true,
            templateOptions: { compilerOptions: {} },
          } as any)

          js = compiled.content
          if (hasScoped && scopeId) {
            // 将 scopeId 挂到默认导出组件上
            js += `\n;import { getCurrentInstance as __getCI } from 'vue'`
            // 简化处理：直接在默认导出对象上设置 __scopeId
            js = js.replace(
              /export default (\w+)/,
              (m, name) => `${name}.__scopeId = ${JSON.stringify(scopeId)};\nexport default ${name}`,
            )
          }
        } else if (descriptor.template) {
          // template-only SFC
          const compiled = compileTemplate({
            source: descriptor.template.content,
            filename: args.path,
            id,
            compilerOptions: {},
          })
          js = [
            compiled.code,
            `const __sfc_component__ = { render }`,
            scopeId ? `__sfc_component__.__scopeId = ${JSON.stringify(scopeId)}` : '',
            `export default __sfc_component__`,
          ]
            .filter(Boolean)
            .join('\n')
        } else {
          js = 'export default {}'
        }

        // 交给 esbuild 处理 TS → JS 与模块图
        return { contents: js, loader: 'ts' }
      })
    },
  }
}
