// src/utils/compileSFC.ts
import { parse, compileScript, compileTemplate, compileStyle } from 'vue/compiler-sfc'

// ── Babel standalone 懒加载 ──
let _babelPromise: Promise<typeof import('@babel/standalone')> | null = null

async function getBabel(): Promise<typeof import('@babel/standalone')> {
  if (!_babelPromise) {
    _babelPromise = import('@babel/standalone')
  }
  return _babelPromise
}

// ── 辅助函数 ──
function hash(str: string): string {
  let h = 0
  for (let i = 0; i < str.length; i++) {
    h = ((h << 5) - h + str.charCodeAt(i)) | 0
  }
  return Math.abs(h).toString(36).slice(0, 8)
}

function transpileTS(code: string, babel: typeof import('@babel/standalone'), isTSX: boolean): string {
  const result = babel.transform(code, {
    filename: 'Component.vue',
    presets: [['typescript', { isTSX, allExtensions: true }]],
  })
  if (!result.code) throw new Error('Babel transform produced no output')
  return result.code.replace(/export\s*\{\s*}\s*;?\s*/g, '').trim()
}

function transformImports(code: string): string {
  const fixDestructure = (s: string) => s.replace(/\s+as\s+/g, ': ')

  return code
    .replace(
      /import\s+\{([^}]+)\}\s+from\s+['"]vue['"]/g,
      (_, imports) => `const { ${fixDestructure(imports)} } = __VUE__`,
    )
    .replace(
      /import\s+\*\s+as\s+(\w+)\s+from\s+['"]([^'"]+)['"]/g,
      (_, name, source) => `const ${name} = __DEPS__[${JSON.stringify(source)}]`,
    )
    .replace(
      /import\s+\{([^}]+)\}\s+from\s+['"]([^'"]+)['"]/g,
      (_, imports, source) => `const { ${fixDestructure(imports)} } = __DEPS__[${JSON.stringify(source)}]`,
    )
    .replace(
      /import\s+(\w+)\s+from\s+['"]([^'"]+)['"]/g,
      (_, name, source) =>
        `const ${name} = __DEPS__[${JSON.stringify(source)}]?.default ?? __DEPS__[${JSON.stringify(source)}]`,
    )
    .replace(/export\s+default\s+/g, 'return ')
    .replace(/export\s+function\s+/g, 'return function ')
}

async function transpileSFCSource(source: string): Promise<string> {
  if (!/\blang\s*=\s*["']tsx?["']/i.test(source)) return source

  const babel = await getBabel()
  const SCRIPT_RE = /<script\b([^>]*)>([\s\S]*?)<\/script>/gi

  return source.replace(SCRIPT_RE, (_match, attrs, content) => {
    const isTSX = /\blang\s*=\s*["']tsx["']/i.test(attrs)
    const isTS = isTSX || /\blang\s*=\s*["']ts["']/i.test(attrs)
    if (!isTS) return _match
    const jsContent = transpileTS(content, babel, isTSX)
    const cleanAttrs = attrs.replace(/\s+lang\s*=\s*["']tsx?["']/i, '')
    return `<script${cleanAttrs}>${jsContent}</script>`
  })
}

export interface SFCCompileResult {
  code: string | null
  css: string
  scopeId: string | null
  hasTemplate: boolean
  hasScript: boolean
}

export async function compileSFC(
  source: string,
  options: { filename?: string } = {},
): Promise<SFCCompileResult> {
  const filename = options.filename || 'Component.vue'

  // 1. TS → JS 预处理
  const jsSource = await transpileSFCSource(source)

  // 2. 解析 SFC
  const { descriptor, errors } = parse(jsSource, { filename, sourceMap: false })
  if (errors.length) throw new Error(errors.join('\n'))

  const id = hash(source + filename)
  const hasScoped = descriptor.styles.some((s) => s.scoped)
  const scopeId = hasScoped ? `data-v-${id}` : null

  let code: string | null = null
  let hasTemplate = false
  let hasScript = false

  // 3. 编译脚本
  if (descriptor.script || descriptor.scriptSetup) {
    hasScript = true
    const compiled = compileScript(descriptor, {
      id,
      genDefaultAs: '__sfc_component__',
      inlineTemplate: true,
      templateOptions: { compilerOptions: {} },
    } as any)

    code = transformImports(compiled.content)
    if (hasScoped) {
      code += `\n__sfc_component__.__scopeId = ${JSON.stringify(scopeId)}`
    }
    code += '\n;return __sfc_component__'
    hasTemplate = !!descriptor.template
  } else if (descriptor.template) {
    hasTemplate = true
    const compiled = compileTemplate({
      source: descriptor.template.content,
      filename,
      id,
      compilerOptions: {},
    })
    let raw = transformImports(compiled.code)
    code = [
      raw,
      `var __sfc_component__ = Vue.defineComponent({ render })`,
      hasScoped ? `__sfc_component__.__scopeId = ${JSON.stringify(scopeId)}` : '',
      `return __sfc_component__`,
    ]
      .filter(Boolean)
      .join('\n')
  }

  // 4. 编译样式
  const cssParts: string[] = []
  for (const style of descriptor.styles) {
    const result = compileStyle({
      source: style.content,
      filename,
      id,
      scoped: style.scoped,
    })
    if (result.code) cssParts.push(result.code)
  }

  return { code, css: cssParts.join('\n'), scopeId, hasTemplate, hasScript }
}

/** 从不完整的 SFC 中提取 <template> 内容，用于流式回退展示 */
export function extractTemplateHTML(source: string): string {
  const match = source.match(/<template>([\s\S]*?)(?:<\/template>|$)/)
  if (!match) return ''

  let html = match[1]
  html = html.replace(/<script[\s\S]*?(?:<\/script>|$)/gi, '')
  html = html.replace(/<style[\s\S]*?(?:<\/style>|$)/gi, '')
  html = html.replace(/\sv-(?:bind|if|else-if|else|for|show|model|on|slot)\.[\w.-]+|:\w+(?:\.\w+)*="[^"]*"/g, '')
  html = html.replace(/\sv-(?:bind|if|else-if|else|for|show|model|on|slot)="[^"]*"/g, '')
  html = html.replace(/\s@\w+(?:\.\w+)*="[^"]*"/g, '')
  html = html.replace(/<(\w+)\s+([^>]*?)\s*\/>/g, '<$1 $2></$1>')

  return html.trim()
}
