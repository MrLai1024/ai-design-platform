# AI Generation App 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `ai-generation-app` 中实现 AI 对话 → 流式生成 Vue SFC → 浏览器端编译 → iframe 沙箱实时渲染

**Architecture:** Composable 驱动，Pinia store 为唯一状态汇合点。数据管道：useStreamChat → useCodeParser → useMultiCompiler → usePreviewRenderer。组件层 ChatPanel / CodeEditor / PreviewFrame 消费 store + composable 方法。

**Tech Stack:** Vue 3.4 + TypeScript + Pinia + @vue/repl + @babel/standalone + Monaco Editor + markdown-it + Vitest

---

## Task 1: 安装依赖与配置测试基础设施

**Files:**
- Modify: `package.json`
- Create: `vitest.config.ts`
- Modify: `tsconfig.json`

- [ ] **Step 1: 安装运行时依赖**

```bash
cd ai-design-platform/ai-design-platform-web/packages/ai-generation-app
pnpm add @vue/repl @babel/standalone monaco-editor markdown-it
```

- [ ] **Step 2: 安装开发/测试依赖**

```bash
pnpm add -D vitest @vue/test-utils happy-dom monaco-editor-webpack-plugin
```

- [ ] **Step 3: 创建 vitest.config.ts**

```typescript
// vitest.config.ts
import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import path from 'path'

export default defineConfig({
  plugins: [vue()],
  test: {
    environment: 'happy-dom',
    include: ['src/**/*.test.ts'],
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
      '@ai-design/shared': path.resolve(__dirname, '../../shared/src'),
      '@ai-design/micro-core': path.resolve(__dirname, '../../micro-core/src'),
    },
  },
})
```

- [ ] **Step 4: 更新 package.json 添加 test 脚本**

Edit `package.json` — 在 `"scripts"` 中添加:

```json
"test": "vitest run",
"test:watch": "vitest"
```

- [ ] **Step 5: 验证测试框架可用**

```bash
pnpm test
```

Expected: "No test files found" 或类似提示（非错误退出）

- [ ] **Step 6: Commit**

```bash
git add package.json pnpm-lock.yaml vitest.config.ts tsconfig.json
git commit -m "chore(ai-generation): add dependencies and vitest config"
```

---

## Task 2: 创建 TypeScript 类型定义

**Files:**
- Create: `src/types/generation.ts`

- [ ] **Step 1: 创建类型文件**

```typescript
// src/types/generation.ts

/** 组件库标识 */
export type ComponentLibrary = 'tailwind' | 'antd' | 'element' | 'echarts'

/** 消息中的代码块 */
export interface ParsedCodeBlock {
  filename: string
  language: string
  code: string
  startLine: number
}

/** 对话消息 */
export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  codeBlocks: ParsedCodeBlock[]
  timestamp: number
  isStreaming: boolean
}

/** 生成的文件条目 */
export interface FileEntry {
  filename: string
  content: string
  language: 'vue' | 'typescript' | 'javascript' | 'css'
  isDirty: boolean
  source: 'ai' | 'user'
}

/** 组件库配置 */
export interface LibraryConfig {
  key: ComponentLibrary
  label: string
  cdnUrls: string[]
  docInjection: string
}

/** 编译结果 */
export interface CompileResult {
  code: string | null
  css: string
  scopeId: string | null
  hasTemplate: boolean
  hasScript: boolean
}

/** 编译选项 */
export interface CompileOptions {
  filename?: string
}
```

- [ ] **Step 2: Commit**

```bash
git add src/types/generation.ts
git commit -m "feat(ai-generation): add TypeScript type definitions"
```

---

## Task 3: 创建 Pinia Generation Store

**Files:**
- Create: `src/stores/generation.ts`

- [ ] **Step 1: 编写 store**

```typescript
// src/stores/generation.ts
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { ChatMessage, FileEntry, ComponentLibrary } from '@/types/generation'

export const useGenerationStore = defineStore('generation', () => {
  // ── State ──
  const messages = ref<ChatMessage[]>([])
  const files = ref<Map<string, FileEntry>>(new Map())
  const activeFile = ref<string | null>(null)
  const isStreaming = ref(false)
  const compiledOutput = ref<string>('')
  const compileError = ref<string | null>(null)
  const currentLib = ref<ComponentLibrary>('tailwind')

  // ── Getters ──
  const lastAssistantMessage = computed(() => {
    for (let i = messages.value.length - 1; i >= 0; i--) {
      if (messages.value[i]!.role === 'assistant') return messages.value[i]!
    }
    return null
  })

  const dirtyFiles = computed(() => {
    const dirty = new Set<string>()
    for (const [name, entry] of files.value) {
      if (entry.isDirty) dirty.add(name)
    }
    return dirty
  })

  const fileList = computed(() => Array.from(files.value.values()))

  const activeFileEntry = computed(() => {
    if (!activeFile.value) return null
    return files.value.get(activeFile.value) ?? null
  })

  // ── Actions ──
  function addMessage(msg: ChatMessage): void {
    messages.value.push(msg)
  }

  function appendToLastMessage(content: string): void {
    const last = messages.value[messages.value.length - 1]
    if (last && last.role === 'assistant') {
      last.content += content
    }
  }

  function finalizeLastMessage(): void {
    const last = messages.value[messages.value.length - 1]
    if (last && last.role === 'assistant') {
      last.isStreaming = false
    }
    isStreaming.value = false
  }

  function setFile(filename: string, entry: FileEntry): void {
    files.value.set(filename, entry)
    if (!activeFile.value) {
      activeFile.value = filename
    }
  }

  function updateFileContent(filename: string, content: string): void {
    const entry = files.value.get(filename)
    if (entry) {
      entry.content = content
      entry.isDirty = true
    }
  }

  function setActiveFile(filename: string): void {
    if (files.value.has(filename)) {
      activeFile.value = filename
    }
  }

  function removeFile(filename: string): void {
    files.value.delete(filename)
    if (activeFile.value === filename) {
      activeFile.value = fileList.value[0]?.filename ?? null
    }
  }

  function addNewFile(filename: string): void {
    const entry: FileEntry = {
      filename,
      content: '',
      language: 'vue',
      isDirty: false,
      source: 'user',
    }
    files.value.set(filename, entry)
    activeFile.value = filename
  }

  function markFileClean(filename: string): void {
    const entry = files.value.get(filename)
    if (entry) entry.isDirty = false
  }

  function setCompiledOutput(output: string): void {
    compiledOutput.value = output
  }

  function setCompileError(error: string | null): void {
    compileError.value = error
  }

  function resetAll(): void {
    messages.value = []
    files.value = new Map()
    activeFile.value = null
    isStreaming.value = false
    compiledOutput.value = ''
    compileError.value = null
  }

  return {
    // state
    messages, files, activeFile, isStreaming, compiledOutput, compileError, currentLib,
    // getters
    lastAssistantMessage, dirtyFiles, fileList, activeFileEntry,
    // actions
    addMessage, appendToLastMessage, finalizeLastMessage,
    setFile, updateFileContent, setActiveFile, removeFile, addNewFile,
    markFileClean, setCompiledOutput, setCompileError, resetAll,
  }
})
```

- [ ] **Step 2: Commit**

```bash
git add src/stores/generation.ts
git commit -m "feat(ai-generation): add Pinia generation store"
```

---

## Task 4: 实现 parseMultiSFC 工具函数

**Files:**
- Create: `src/utils/parseMultiSFC.ts`
- Create: `src/utils/parseMultiSFC.test.ts`

- [ ] **Step 1: 编写测试**

```typescript
// src/utils/parseMultiSFC.test.ts
import { describe, it, expect } from 'vitest'
import { parseMultiSFC, parseSingleCodeBlock } from './parseMultiSFC'

describe('parseMultiSFC', () => {
  it('parses multi-file with ## heading markers', () => {
    const input = `
## App.vue
\`\`\`vue
<template>
  <div>Hello</div>
</template>
\`\`\`

## UserList.vue
\`\`\`vue
<template>
  <ul><li v-for="u in users">{{ u }}</li></ul>
</template>
\`\`\`
`
    const result = parseMultiSFC(input)
    expect(result).toHaveLength(2)
    expect(result[0]!.filename).toBe('App.vue')
    expect(result[0]!.code).toContain('<div>Hello</div>')
    expect(result[1]!.filename).toBe('UserList.vue')
    expect(result[1]!.code).toContain('v-for')
  })

  it('returns empty array when no headings found', () => {
    const input = 'Just some text without headings'
    expect(parseMultiSFC(input)).toEqual([])
  })

  it('handles headings without code fences gracefully', () => {
    const input = '## App.vue\nNo code block here'
    expect(parseMultiSFC(input)).toEqual([])
  })

  it('handles incomplete streaming content', () => {
    const input = '## App.vue\n```vue\n<template>\n  <div>Incomplete'
    const result = parseMultiSFC(input)
    expect(result).toHaveLength(0) // no closing fence yet
  })
})

describe('parseSingleCodeBlock', () => {
  it('extracts the first vue code block when no headings present', () => {
    const input = 'Here is some code:\n```vue\n<template><div>Hi</div></template>\n```'
    const result = parseSingleCodeBlock(input)
    expect(result).not.toBeNull()
    expect(result!.filename).toBe('App.vue')
    expect(result!.code).toContain('<div>Hi</div>')
  })

  it('returns null when no code block found', () => {
    expect(parseSingleCodeBlock('No code here')).toBeNull()
  })
})
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pnpm test src/utils/parseMultiSFC.test.ts
```

Expected: FAIL — module not found

- [ ] **Step 3: 实现 parseMultiSFC**

```typescript
// src/utils/parseMultiSFC.ts
import type { ParsedCodeBlock } from '@/types/generation'

/**
 * 从流式累积的 AI 回复中提取多文件 SFC。
 * 格式: ## FileName.vue\n```vue\n...code...\n```
 */
export function parseMultiSFC(text: string): ParsedCodeBlock[] {
  const headingRe = /^#{2,3}\s+(.+?\.vue)\b/gm
  const fenceRe = /```vue\s*\n([\s\S]*?)```/g

  const headings: Array<{ filename: string; matchEnd: number; matchStart: number }> = []
  let m: RegExpExecArray | null
  while ((m = headingRe.exec(text)) !== null) {
    headings.push({ filename: m[1] || '', matchStart: m.index, matchEnd: m.index + m[0].length })
  }

  if (headings.length === 0) return []

  const files: ParsedCodeBlock[] = []
  for (let i = 0; i < headings.length; i++) {
    const { filename, matchEnd } = headings[i]!
    const end = i + 1 < headings.length ? headings[i + 1]!.matchStart : text.length
    const section = text.slice(matchEnd, end)

    fenceRe.lastIndex = 0
    const fenceMatch = fenceRe.exec(section)
    if (fenceMatch) {
      files.push({
        filename,
        language: 'vue',
        code: (fenceMatch[1] || '').trim(),
        startLine: matchEnd,
      })
    }
  }

  return files
}

/**
 * 当无多文件标记时，提取第一个 ```vue 代码块作为 App.vue
 */
export function parseSingleCodeBlock(text: string): ParsedCodeBlock | null {
  const fenceRe = /```(?:vue|html)\s*\n([\s\S]*?)```/
  const match = fenceRe.exec(text)
  if (!match) return null

  return {
    filename: 'App.vue',
    language: 'vue',
    code: (match[1] || '').trim(),
    startLine: match.index,
  }
}
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pnpm test src/utils/parseMultiSFC.test.ts
```

Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/utils/parseMultiSFC.ts src/utils/parseMultiSFC.test.ts
git commit -m "feat(ai-generation): add parseMultiSFC utility"
```

---

## Task 5: 实现 securityScan 工具函数

**Files:**
- Create: `src/utils/securityScan.ts`
- Create: `src/utils/securityScan.test.ts`

- [ ] **Step 1: 编写测试**

```typescript
// src/utils/securityScan.test.ts
import { describe, it, expect } from 'vitest'
import { scanCode } from './securityScan'

describe('scanCode', () => {
  it('returns null for safe code', () => {
    expect(scanCode('const x = 1 + 2')).toBeNull()
    expect(scanCode('<template><div>Hello</div></template>')).toBeNull()
  })

  it('detects document.cookie', () => {
    expect(scanCode('document.cookie = "x"')).toContain('document.cookie')
  })

  it('detects eval()', () => {
    expect(scanCode('eval("alert(1)")')).toContain('eval()')
  })

  it('detects new Function()', () => {
    expect(scanCode('new Function("return 1")')).toContain('new Function()')
  })

  it('detects window.top access', () => {
    expect(scanCode('window.top.location')).toContain('window.top')
  })

  it('detects localStorage', () => {
    expect(scanCode('localStorage.setItem("k", "v")')).toContain('localStorage')
  })

  it('returns first match when multiple patterns found', () => {
    const result = scanCode('document.cookie; eval("x")')
    expect(result).toContain('document.cookie')
  })
})
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pnpm test src/utils/securityScan.test.ts
```

Expected: FAIL

- [ ] **Step 3: 实现 securityScan**

```typescript
// src/utils/securityScan.ts

const DANGEROUS_PATTERNS: Array<[RegExp, string]> = [
  [/document\s*\.\s*cookie/, 'document.cookie'],
  [/document\s*\.\s*domain/, 'document.domain'],
  [/document\s*\.\s*write/, 'document.write'],
  [/\blocalStorage\b/, 'localStorage'],
  [/\bsessionStorage\b/, 'sessionStorage'],
  [/eval\s*\(/, 'eval()'],
  [/new\s+Function\s*\(/, 'new Function()'],
  [/\bwindow\s*\.\s*top\b/, 'window.top'],
  [/\bwindow\s*\.\s*parent\b/, 'window.parent'],
  [/\bwindow\s*\.\s*opener\b/, 'window.opener'],
  [/__proto__/, '__proto__'],
  [/constructor\s*\[/, 'constructor[]'],
  [/import\s*\(/, 'import()'],
  [/fetch\s*\(\s*['"]https?:\/\//, 'fetch() to external URL'],
  [/XMLHttpRequest/, 'XMLHttpRequest'],
]

/**
 * 扫描编译产物中的危险调用，返回第一个匹配的警告信息；
 * 无危险调用时返回 null。
 */
export function scanCode(code: string): string | null {
  for (const [pattern, label] of DANGEROUS_PATTERNS) {
    if (pattern.test(code)) {
      return `代码包含不安全调用: ${label}`
    }
  }
  return null
}
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pnpm test src/utils/securityScan.test.ts
```

Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/utils/securityScan.ts src/utils/securityScan.test.ts
git commit -m "feat(ai-generation): add security scan utility"
```

---

## Task 6: 实现 compileSFC 工具函数

**Files:**
- Create: `src/utils/compileSFC.ts`

- [ ] **Step 1: 实现 compileSFC**

（此函数直接参考 AI2WEB `compileSFC.ts`——使用 `vue/compiler-sfc` 的 `parse`/`compileScript`/`compileTemplate`/`compileStyle` + `@babel/standalone` TS 预处理。文件已有完整实现，此处直接写入。）

```typescript
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
```

- [ ] **Step 2: Commit**

```bash
git add src/utils/compileSFC.ts
git commit -m "feat(ai-generation): add SFC compile utility"
```

> **Note:** `compileSFC` 测试需要 mock `@babel/standalone` 和 `vue/compiler-sfc`，集成验证阶段通过实际组件测试覆盖。

---

## Task 7: 实现 buildPreviewHtml 工具函数

**Files:**
- Create: `src/utils/buildPreviewHtml.ts`
- Create: `src/utils/buildPreviewHtml.test.ts`

- [ ] **Step 1: 编写测试**

```typescript
// src/utils/buildPreviewHtml.test.ts
import { describe, it, expect } from 'vitest'
import { buildPreviewHtml } from './buildPreviewHtml'

describe('buildPreviewHtml', () => {
  it('wraps compiled code in complete HTML document', () => {
    const html = buildPreviewHtml('const app = {}', 'body { color: red; }', ['https://cdn.example.com/lib.js'])
    expect(html).toContain('<!DOCTYPE html>')
    expect(html).toContain('<script src="https://cdn.example.com/lib.js">')
    expect(html).toContain('body { color: red; }')
    expect(html).toContain('const app = {}')
    expect(html).toContain('window.onerror')
    expect(html).toContain('postMessage')
    expect(html).toContain('__VUE__')
    expect(html).toContain('__DEPS__')
  })

  it('works with empty CSS', () => {
    const html = buildPreviewHtml('code', '', [])
    expect(html).toContain('code')
    expect(html).not.toContain('undefined')
  })

  it('works with no CDN urls', () => {
    const html = buildPreviewHtml('code', 'css', [])
    expect(html).not.toContain('<script src=')
  })
})
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pnpm test src/utils/buildPreviewHtml.test.ts
```

Expected: FAIL

- [ ] **Step 3: 实现 buildPreviewHtml**

```typescript
// src/utils/buildPreviewHtml.ts

/**
 * 构建注入 iframe srcdoc 的完整 HTML 文档。
 * 包含 Vue runtime、组件库 CDN、编译产物、错误边界。
 */
export function buildPreviewHtml(
  compiledCode: string,
  compiledCSS: string,
  cdnUrls: string[],
): string {
  const cdnTags = cdnUrls
    .map((url) => {
      if (url.endsWith('.css')) return `<link rel="stylesheet" href="${url}">`
      return `<script src="${url}"><\/script>`
    })
    .join('\n')

  return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <script src="https://unpkg.com/vue@3/dist/vue.global.prod.js"><\/script>
  ${cdnTags}
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
    ${compiledCSS}
  </style>
</head>
<body>
  <div id="app"></div>
  <script>
    (function() {
      var __VUE__ = Vue;
      var __DEPS__ = {};
      var components = {};

      function mountComponent(code) {
        try {
          var fn = new Function('__VUE__', '__DEPS__', code);
          var component = fn(__VUE__, __DEPS__);
          var app = Vue.createApp(component);
          app.mount('#app');
        } catch (e) {
          window.parent.postMessage({ type: 'err', message: 'Mount error: ' + e.message }, '*');
        }
      }

      ${compiledCode ? `mountComponent(${JSON.stringify(compiledCode)});` : '// no compiled code'}
    })();
  <\/script>
  <script>
    window.onerror = function(msg, url, line, col, error) {
      window.parent.postMessage({
        type: 'err',
        message: 'Runtime: ' + msg + ' at line ' + line
      }, '*');
    };
    window.parent.postMessage({ type: 'ready' }, '*');
  <\/script>
</body>
</html>`
}
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pnpm test src/utils/buildPreviewHtml.test.ts
```

Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/utils/buildPreviewHtml.ts src/utils/buildPreviewHtml.test.ts
git commit -m "feat(ai-generation): add buildPreviewHtml utility"
```

---

## Task 8: 实现 useComponentDocs Composable

**Files:**
- Create: `src/composables/useComponentDocs.ts`

- [ ] **Step 1: 实现 useComponentDocs**

```typescript
// src/composables/useComponentDocs.ts
import { ref } from 'vue'
import type { ComponentLibrary, LibraryConfig } from '@/types/generation'

const LIBRARY_CONFIGS: Record<ComponentLibrary, LibraryConfig> = {
  tailwind: {
    key: 'tailwind',
    label: 'Tailwind CSS',
    cdnUrls: ['https://cdn.tailwindcss.com'],
    docInjection: `样式使用 Tailwind CSS 工具类，直接写在 class 属性中。例如 class="flex items-center gap-4 p-6 bg-white rounded-lg shadow-md"。
不要使用 <style scoped> 写自定义 CSS，优先使用 Tailwind 工具类。`,
  },
  antd: {
    key: 'antd',
    label: 'Ant Design Vue',
    cdnUrls: [
      'https://unpkg.com/ant-design-vue@4/dist/antd.min.js',
      'https://unpkg.com/ant-design-vue@4/dist/reset.css',
    ],
    docInjection: `你可以使用 Ant Design Vue 4.x 组件库。可用组件包括：
- 通用: Button, Icon, Typography (Title, Text, Paragraph)
- 布局: Grid (Row, Col), Layout (Header, Footer, Sider, Content), Space, Divider
- 导航: Menu, Breadcrumb, Pagination, Steps, Tabs, Dropdown
- 数据录入: Form, FormItem, Input, InputNumber, Textarea, Select, Option, Checkbox, Radio, Switch, DatePicker, TimePicker, Upload, Rate, Slider
- 数据展示: Table, Tag, Card, List, Tree, Tooltip, Popover, Badge, Avatar, Calendar, Carousel, Collapse, Descriptions, Empty, Image, Statistic, Timeline
- 反馈: Modal, Drawer, Message, Notification, Popconfirm, Progress, Result, Skeleton, Spin, Alert
- 其他: ConfigProvider, Affix, Anchor, BackTop, Watermark

使用示例：
\`\`\`vue
<a-button type="primary" @click="handleClick">提交</a-button>
<a-table :columns="columns" :data-source="data" bordered />
<a-modal v-model:open="visible" title="标题">内容</a-modal>
\`\`\`

注意: 组件名前缀为 a-，如 <a-button>、<a-table>、<a-modal>。`,
  },
  element: {
    key: 'element',
    label: 'Element Plus',
    cdnUrls: [
      'https://unpkg.com/element-plus/dist/index.full.min.js',
      'https://unpkg.com/element-plus/dist/index.css',
    ],
    docInjection: `你可以使用 Element Plus 组件库。组件名前缀为 el-，如 <el-button>、<el-table>、<el-dialog>。
常用组件: Button, Table, Form, Dialog, Input, Select, DatePicker, Upload, Menu, Tabs, Card, Tag, Pagination, Popover, Tooltip, Drawer, Message, Notification, Tree, Cascader, Transfer 等。`,
  },
  echarts: {
    key: 'echarts',
    label: 'ECharts',
    cdnUrls: ['https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js'],
    docInjection: `你可以使用 ECharts 5.x 图表库。需要在 onMounted 中初始化图表：

\`\`\`vue
<script setup>
import { ref, onMounted } from 'vue'
const chartRef = ref(null)
onMounted(() => {
  const chart = echarts.init(chartRef.value)
  chart.setOption({
    title: { text: '图表标题' },
    xAxis: { data: ['A', 'B', 'C'] },
    yAxis: {},
    series: [{ data: [1, 2, 3], type: 'bar' }]
  })
})
</script>
<template>
  <div ref="chartRef" style="width:100%;height:400px"></div>
</template>
\`\`\`

注意: echarts 是全局变量，无需 import，直接使用 echarts.init()。同时需设置容器宽高。`,
  },
}

export function useComponentDocs() {
  const currentLib = ref<ComponentLibrary>('tailwind')

  function setLibrary(lib: ComponentLibrary): void {
    currentLib.value = lib
  }

  function getConfig(): LibraryConfig {
    return LIBRARY_CONFIGS[currentLib.value]
  }

  function getSystemPrompt(): string {
    const config = getConfig()
    const base = `你是一个专业的 Vue 3 单文件组件（SFC）生成助手。

你必须只生成 Vue SFC 代码，使用 <script setup lang="ts"> 语法。

输出格式要求：
- 如果需要生成多个文件，用 "## FileName.vue" 作为每个文件的标题
- 每个文件的代码放在 \`\`\`vue 代码块中
- 只输出代码块和文件标题，不要添加额外的解释说明
- 每个组件必须是完整可运行的 SFC（包含 template, script setup, style）
- 在 script 中 import 其他组件时，文件名必须与你输出的 ## 标题一致`

    const format = `

重要：你的回复必须只包含代码块和文件标题。不要输出任何解释性文字。`

    return [base, config.docInjection, format].join('\n\n')
  }

  return { currentLib, setLibrary, getConfig, getSystemPrompt, libraryConfigs: LIBRARY_CONFIGS }
}
```

- [ ] **Step 2: Commit**

```bash
git add src/composables/useComponentDocs.ts
git commit -m "feat(ai-generation): add useComponentDocs composable"
```

---

## Task 9: 实现 useStreamChat Composable

**Files:**
- Create: `src/composables/useStreamChat.ts`

- [ ] **Step 1: 实现 useStreamChat**

```typescript
// src/composables/useStreamChat.ts
import { ref } from 'vue'
import { useGenerationStore } from '@/stores/generation'
import { useComponentDocs } from './useComponentDocs'
import type { ChatMessage, ComponentLibrary } from '@/types/generation'

function generateId(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 9)
}

export function useStreamChat() {
  const store = useGenerationStore()
  const { currentLib, getSystemPrompt } = useComponentDocs()
  const error = ref<string | null>(null)
  let abortController: AbortController | null = null

  async function send(content: string, lib?: ComponentLibrary): Promise<void> {
    error.value = null
    if (lib) store.currentLib = lib

    // 1. 添加用户消息
    const userMsg: ChatMessage = {
      id: generateId(),
      role: 'user',
      content,
      codeBlocks: [],
      timestamp: Date.now(),
      isStreaming: false,
    }
    store.addMessage(userMsg)

    // 2. 创建空的 assistant 消息
    const assistantMsg: ChatMessage = {
      id: generateId(),
      role: 'assistant',
      content: '',
      codeBlocks: [],
      timestamp: Date.now(),
      isStreaming: true,
    }
    store.addMessage(assistantMsg)
    store.isStreaming = true

    // 3. 构建请求 body
    abortController = new AbortController()
    const systemPrompt = getSystemPrompt()

    const requestMessages = [
      { role: 'system', content: systemPrompt },
      ...store.messages
        .filter((m) => !m.isStreaming) // exclude incomplete assistant message
        .map((m) => ({ role: m.role, content: m.content })),
    ]

    try {
      const response = await fetch('/api/v1/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          messages: requestMessages,
          model: 'glm-5.2',
          stream: true,
        }),
        signal: abortController.signal,
      })

      if (!response.ok) {
        throw new Error(`后端返回错误: ${response.status} ${response.statusText}`)
      }

      const reader = response.body!.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          try {
            const event = JSON.parse(line.slice(6))
            if (event.content) {
              store.appendToLastMessage(event.content)
            }
            if (event.error) {
              error.value = event.error
            }
          } catch {
            // JSON 解析失败，跳过该行
          }
        }
      }
    } catch (e: unknown) {
      if (e instanceof DOMException && e.name === 'AbortError') {
        return // 用户取消
      }
      error.value = e instanceof Error ? e.message : '未知错误'
      store.appendToLastMessage(`\n\n> ⚠️ 生成失败: ${error.value}`)
    } finally {
      store.finalizeLastMessage()
      abortController = null
    }
  }

  function cancel(): void {
    abortController?.abort()
    store.isStreaming = false
  }

  return { send, cancel, error, isStreaming: () => store.isStreaming }
}
```

- [ ] **Step 2: Commit**

```bash
git add src/composables/useStreamChat.ts
git commit -m "feat(ai-generation): add useStreamChat composable"
```

---

## Task 10: 实现 useCodeParser Composable

**Files:**
- Create: `src/composables/useCodeParser.ts`

- [ ] **Step 1: 实现 useCodeParser**

```typescript
// src/composables/useCodeParser.ts
import { watch } from 'vue'
import { useGenerationStore } from '@/stores/generation'
import { parseMultiSFC, parseSingleCodeBlock } from '@/utils/parseMultiSFC'
import type { FileEntry, ParsedCodeBlock } from '@/types/generation'

export function useCodeParser() {
  const store = useGenerationStore()

  // 监听最后一条 AI 消息的 content 变化，实时解析代码块
  watch(
    () => store.lastAssistantMessage?.content,
    (content) => {
      if (!content) return
      const blocks = detectCodeBlocks(content)
      if (blocks.length > 0) {
        updateFiles(blocks)
      }
    },
  )

  function detectCodeBlocks(text: string): ParsedCodeBlock[] {
    // 先尝试多文件解析
    const multi = parseMultiSFC(text)
    if (multi.length > 0) return multi

    // 无多文件标记 → 单文件模式
    const single = parseSingleCodeBlock(text)
    if (single) return [single]

    return []
  }

  function updateFiles(blocks: ParsedCodeBlock[]): void {
    for (const block of blocks) {
      const existing = store.files.get(block.filename)

      // 消重：内容相同则跳过
      if (existing && existing.content === block.code) continue

      const entry: FileEntry = {
        filename: block.filename,
        content: block.code,
        language: 'vue',
        isDirty: true,
        source: 'ai',
      }
      store.setFile(block.filename, entry)
    }

    // 自动切换到第一个文件
    if (blocks.length > 0 && blocks[0]) {
      store.setActiveFile(blocks[0].filename)
    }
  }

  // 同时更新消息中的 codeBlocks 元数据
  watch(
    () => store.lastAssistantMessage?.content,
    (content) => {
      if (!content || !store.lastAssistantMessage) return
      const blocks = detectCodeBlocks(content)
      if (blocks.length > 0) {
        store.lastAssistantMessage.codeBlocks = blocks
      }
    },
  )

  return { detectCodeBlocks }
}
```

- [ ] **Step 2: Commit**

```bash
git add src/composables/useCodeParser.ts
git commit -m "feat(ai-generation): add useCodeParser composable"
```

---

## Task 11: 实现 useMultiCompiler Composable

**Files:**
- Create: `src/composables/useMultiCompiler.ts`

- [ ] **Step 1: 实现 useMultiCompiler**

```typescript
// src/composables/useMultiCompiler.ts
import { watch, ref } from 'vue'
import { useGenerationStore } from '@/stores/generation'
import { compileSFC } from '@/utils/compileSFC'

export function useMultiCompiler() {
  const store = useGenerationStore()
  const isCompiling = ref(false)
  let debounceTimer: ReturnType<typeof setTimeout> | null = null
  let compileGeneration = 0
  const DEBOUNCE_MS = 300

  // 监听 dirty 文件变化，触发 debounced 编译
  watch(
    () => store.dirtyFiles,
    () => {
      if (store.dirtyFiles.size === 0) return
      scheduleCompile()
    },
    { deep: true },
  )

  // 监听当前文件手动编辑（用户编辑后触发）
  watch(
    () => store.activeFileEntry?.content,
    () => {
      const entry = store.activeFileEntry
      if (entry && entry.source === 'user' && entry.isDirty) {
        scheduleCompile()
      }
    },
  )

  function scheduleCompile(): void {
    if (debounceTimer) clearTimeout(debounceTimer)
    debounceTimer = setTimeout(() => doCompile(), DEBOUNCE_MS)
  }

  async function doCompile(): Promise<void> {
    const gen = ++compileGeneration
    store.compileError = null
    isCompiling.value = true

    // 收集所有需要编译的文件
    const filesToCompile = Array.from(store.dirtyFiles)
    // 也加入当前活动文件（如果有的话），确保预览完整
    if (store.activeFile && !store.dirtyFiles.has(store.activeFile)) {
      filesToCompile.push(store.activeFile)
    }

    // 至少编译活动文件
    if (filesToCompile.length === 0 && store.activeFileEntry) {
      filesToCompile.push(store.activeFileEntry.filename)
    }

    const results: Array<{ filename: string; code: string | null; css: string }> = []

    for (const filename of filesToCompile) {
      const file = store.files.get(filename)
      if (!file || !file.content.trim()) continue

      try {
        const compiled = await compileSFC(file.content, { filename })
        if (gen !== compileGeneration) return // 过期编译，丢弃

        if (compiled.code) {
          results.push({ filename, code: compiled.code, css: compiled.css })
          store.markFileClean(filename)
        }
      } catch {
        if (gen !== compileGeneration) return
        // 编译失败时的错误在 compileSFC 中处理
      }
    }

    if (gen !== compileGeneration) return
    isCompiling.value = false

    // 合并编译结果
    if (results.length === 0) {
      store.setCompiledOutput('')
      return
    }

    // 对于多文件，将活动文件作为主组件
    const activeResult = results.find((r) => r.filename === store.activeFile) || results[0]!
    const otherResults = results.filter((r) => r !== activeResult)

    const mergedCSS = results.map((r) => r.css).filter(Boolean).join('\n')

    // 生成可执行的 register 代码：主组件 + 子组件注册
    let finalCode = ''
    if (otherResults.length > 0) {
      finalCode += `// 注册子组件\n`
      for (const r of otherResults) {
        const name = r.filename.replace(/\.vue$/, '')
        finalCode += `__DEPS__['./${r.filename}'] = (function() { ${r.code} })();\n`
      }
    }
    finalCode += `\n// 主组件\n${activeResult.code || '// no compiled code'}`
    finalCode += '\n// CSS\n__CSS__ = ' + JSON.stringify(mergedCSS) + ';'

    store.setCompiledOutput(finalCode)
  }

  function compileNow(): void {
    if (debounceTimer) clearTimeout(debounceTimer)
    doCompile()
  }

  return { isCompiling, compileNow }
}
```

- [ ] **Step 2: Commit**

```bash
git add src/composables/useMultiCompiler.ts
git commit -m "feat(ai-generation): add useMultiCompiler composable"
```

---

## Task 12: 实现 usePreviewRenderer Composable

**Files:**
- Create: `src/composables/usePreviewRenderer.ts`

- [ ] **Step 1: 实现 usePreviewRenderer**

```typescript
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
    if (!iframeRef.value?.contentWindow) return
    const cdnUrls = getConfig().cdnUrls
    const html = buildPreviewHtml(compiledCode, compiledCSS, cdnUrls)
    iframeRef.value.srcdoc = html
    // srcdoc 设置后会触发 iframe 重载，iframe 加载完成后会 postMessage({type:'ready'})
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
      // 提取 CSS（从 compiledOutput 格式）
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
      const cssMatch = store.compiledOutput.match(/__CSS__\s*=\s*["']([^"']*)["']/)
      if (cssMatch) {
        css = cssMatch[1] || ''
        code = store.compiledOutput.replace(/\/\/ CSS\n__CSS__.*$/, '')
      }
      sendToFrame(code, css)
    }
  }

  return { iframeRef, iframeReady, errorMessage, refresh }
}
```

- [ ] **Step 2: Commit**

```bash
git add src/composables/usePreviewRenderer.ts
git commit -m "feat(ai-generation): add usePreviewRenderer composable"
```

---

## Task 13: ChatInput 组件

**Files:**
- Create: `src/components/ChatInput.vue`

- [ ] **Step 1: 实现 ChatInput**

```vue
<!-- src/components/ChatInput.vue -->
<script setup lang="ts">
import { ref } from 'vue'
import type { ComponentLibrary } from '@/types/generation'

const emit = defineEmits<{
  send: [content: string, lib: ComponentLibrary]
}>()

const props = defineProps<{
  isStreaming: boolean
  currentLib: ComponentLibrary
}>()

const inputText = ref('')
const LIB_OPTIONS: Array<{ key: ComponentLibrary; label: string }> = [
  { key: 'tailwind', label: 'Tailwind CSS' },
  { key: 'antd', label: 'Ant Design Vue' },
  { key: 'element', label: 'Element Plus' },
  { key: 'echarts', label: 'ECharts' },
]

function handleSend(): void {
  const text = inputText.value.trim()
  if (!text || props.isStreaming) return
  emit('send', text, props.currentLib)
  inputText.value = ''
}

function handleKeydown(e: KeyboardEvent): void {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  }
}
</script>

<template>
  <div class="chat-input border-t border-gray-200 p-4 bg-white">
    <div class="flex items-center gap-2 mb-2">
      <select
        :value="currentLib"
        @change="$emit('update:currentLib', ($event.target as HTMLSelectElement).value as ComponentLibrary)"
        class="text-xs border border-gray-300 rounded px-2 py-1 bg-white text-gray-600"
      >
        <option v-for="opt in LIB_OPTIONS" :key="opt.key" :value="opt.key">
          {{ opt.label }}
        </option>
      </select>
    </div>
    <div class="flex gap-2">
      <textarea
        v-model="inputText"
        @keydown="handleKeydown"
        :disabled="isStreaming"
        placeholder="描述你想要生成的组件..."
        rows="2"
        class="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:bg-gray-100"
      />
      <button
        v-if="!isStreaming"
        @click="handleSend"
        :disabled="!inputText.trim()"
        class="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        发送
      </button>
      <button
        v-else
        @click="$emit('cancel')"
        class="px-4 py-2 bg-red-600 text-white rounded-lg text-sm font-medium hover:bg-red-700 transition-colors"
      >
        取消
      </button>
    </div>
  </div>
</template>
```

- [ ] **Step 2: Commit**

```bash
git add src/components/ChatInput.vue
git commit -m "feat(ai-generation): add ChatInput component"
```

---

## Task 14: FileTabBar 组件

**Files:**
- Create: `src/components/FileTabBar.vue`

- [ ] **Step 1: 实现 FileTabBar**

```vue
<!-- src/components/FileTabBar.vue -->
<script setup lang="ts">
import type { FileEntry } from '@/types/generation'

defineProps<{
  files: FileEntry[]
  activeFile: string | null
}>()

const emit = defineEmits<{
  select: [filename: string]
  close: [filename: string]
  add: []
}>()
</script>

<template>
  <div class="file-tab-bar flex items-center bg-gray-100 border-b border-gray-200 overflow-x-auto">
    <button
      v-for="file in files"
      :key="file.filename"
      @click="emit('select', file.filename)"
      :class="[
        'flex items-center gap-1.5 px-3 py-1.5 text-xs border-r border-gray-200 whitespace-nowrap transition-colors',
        activeFile === file.filename
          ? 'bg-white text-blue-600 border-t-2 border-t-blue-600'
          : 'bg-transparent text-gray-600 hover:bg-gray-50',
      ]"
    >
      <span class="font-mono">{{ file.filename }}</span>
      <span v-if="file.isDirty" class="w-2 h-2 rounded-full bg-orange-400" title="未保存的更改" />
      <button
        @click.stop="emit('close', file.filename)"
        class="ml-1 text-gray-400 hover:text-red-500 text-lg leading-none"
        title="关闭文件"
      >
        &times;
      </button>
    </button>
    <button
      @click="emit('add')"
      class="px-3 py-1.5 text-xs text-gray-500 hover:text-blue-600 hover:bg-gray-50 border-r border-gray-200 transition-colors"
      title="新建文件"
    >
      +
    </button>
  </div>
</template>
```

- [ ] **Step 2: Commit**

```bash
git add src/components/FileTabBar.vue
git commit -m "feat(ai-generation): add FileTabBar component"
```

---

## Task 15: ChatPanel 组件

**Files:**
- Create: `src/components/ChatPanel.vue`

- [ ] **Step 1: 实现 ChatPanel**

```vue
<!-- src/components/ChatPanel.vue -->
<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'
import { useGenerationStore } from '@/stores/generation'
import { useStreamChat } from '@/composables/useStreamChat'
import ChatInput from './ChatInput.vue'

const store = useGenerationStore()
const { send, cancel } = useStreamChat()
const messagesContainer = ref<HTMLElement | null>(null)

// 新消息时自动滚到底部
watch(
  () => store.messages.length,
  async () => {
    await nextTick()
    if (messagesContainer.value) {
      messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
    }
  },
)

// 流式内容更新时也滚动
watch(
  () => store.lastAssistantMessage?.content,
  async () => {
    await nextTick()
    if (messagesContainer.value) {
      messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
    }
  },
)

function handleSend(content: string, lib: Parameters<typeof send>[1]): void {
  send(content, lib)
}

function renderMessageContent(content: string): string {
  // 简单 markdown 渲染（代码块之外的内容）
  return content
    .replace(/```[\s\S]*?```/g, '') // 移除代码块（由代码卡片单独展示）
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\n/g, '<br>')
}

function hasCodeBlocks(msg: typeof store.messages[number]): boolean {
  return msg.codeBlocks.length > 0
}
</script>

<template>
  <div class="chat-panel flex flex-col h-full bg-white">
    <div class="px-4 py-3 border-b border-gray-200 bg-gray-50">
      <h2 class="text-sm font-semibold text-gray-700">AI 代码生成</h2>
    </div>

    <div ref="messagesContainer" class="flex-1 overflow-y-auto px-4 py-3 space-y-4">
      <div v-if="store.messages.length === 0" class="text-center text-gray-400 mt-8">
        <p class="text-lg mb-2">👋 描述你想要生成的组件</p>
        <p class="text-xs">例如："用表格展示用户列表，包含姓名、邮箱、状态列"</p>
      </div>

      <div
        v-for="msg in store.messages"
        :key="msg.id"
        :class="[
          'message flex',
          msg.role === 'user' ? 'justify-end' : 'justify-start',
        ]"
      >
        <div
          :class="[
            'max-w-[90%] rounded-lg px-4 py-2.5 text-sm',
            msg.role === 'user'
              ? 'bg-blue-600 text-white'
              : 'bg-gray-100 text-gray-800',
          ]"
        >
          <!-- 文本内容 -->
          <div v-if="msg.role === 'user'">{{ msg.content }}</div>
          <div
            v-else
            class="message-content prose prose-sm max-w-none"
            v-html="renderMessageContent(msg.content)"
          />

          <!-- 代码生成卡片 -->
          <div
            v-if="msg.role === 'assistant' && hasCodeBlocks(msg)"
            class="mt-2 pt-2 border-t border-gray-200"
          >
            <div class="text-xs text-gray-500 mb-1">生成了 {{ msg.codeBlocks.length }} 个文件：</div>
            <div class="flex flex-wrap gap-1">
              <span
                v-for="block in msg.codeBlocks"
                :key="block.filename"
                class="inline-block px-2 py-0.5 text-xs bg-blue-50 text-blue-700 rounded border border-blue-200 font-mono"
              >
                {{ block.filename }}
              </span>
            </div>
          </div>

          <!-- 流式输出指示器 -->
          <span
            v-if="msg.isStreaming && !msg.content"
            class="inline-block w-2 h-4 bg-gray-400 animate-pulse"
          />
        </div>
      </div>
    </div>

    <ChatInput
      :is-streaming="store.isStreaming"
      :current-lib="store.currentLib"
      @send="handleSend"
      @cancel="cancel"
      @update:current-lib="store.currentLib = $event"
    />
  </div>
</template>
```

- [ ] **Step 2: Commit**

```bash
git add src/components/ChatPanel.vue
git commit -m "feat(ai-generation): add ChatPanel component"
```

---

## Task 16: CodeEditor 组件

**Files:**
- Create: `src/components/CodeEditor.vue`

- [ ] **Step 1: 实现 CodeEditor**

```vue
<!-- src/components/CodeEditor.vue -->
<script setup lang="ts">
import { ref, watch, shallowRef, onMounted } from 'vue'
import { useGenerationStore } from '@/stores/generation'
import FileTabBar from './FileTabBar.vue'

const store = useGenerationStore()
const editorContainer = ref<HTMLElement | null>(null)
let editor: import('monaco-editor').editor.IStandaloneCodeEditor | null = null

// 懒加载 Monaco
onMounted(async () => {
  if (!editorContainer.value) return
  const monaco = await import('monaco-editor')
  editor = monaco.editor.create(editorContainer.value, {
    value: store.activeFileEntry?.content || '',
    language: 'html', // Vue SFC 使用 HTML 语法高亮
    theme: 'vs',
    minimap: { enabled: false },
    fontSize: 13,
    lineNumbers: 'on',
    scrollBeyondLastLine: false,
    wordWrap: 'on',
    automaticLayout: true,
    tabSize: 2,
  })

  editor.onDidChangeModelContent(() => {
    if (!store.activeFile || !editor) return
    const value = editor.getValue()
    store.updateFileContent(store.activeFile, value)
  })

  // 初始内容
  if (store.activeFileEntry) {
    editor.setValue(store.activeFileEntry.content)
  }
})

// 切换文件时更新编辑器内容
watch(
  () => store.activeFile,
  () => {
    if (!editor || !store.activeFileEntry) return
    const model = editor.getModel()
    if (model) {
      model.setValue(store.activeFileEntry.content)
    }
  },
)

// Ctrl+S 触发立即编译
function handleKeydown(e: KeyboardEvent): void {
  if ((e.ctrlKey || e.metaKey) && e.key === 's') {
    e.preventDefault()
    // 编译由外部 composable 的 watch 触发，这里只需确保 isDirty 已设置
  }
}

function handleFileClose(filename: string): void {
  store.removeFile(filename)
}

function handleFileAdd(): void {
  const name = prompt('文件名（含 .vue 后缀）：', 'NewComponent.vue')
  if (!name) return
  // 确保有后缀
  const filename = name.endsWith('.vue') ? name : `${name}.vue`
  store.addNewFile(filename)
}
</script>

<template>
  <div class="code-editor flex flex-col h-full bg-white">
    <div class="px-4 py-2 border-b border-gray-200 bg-gray-50 flex items-center justify-between">
      <h2 class="text-sm font-semibold text-gray-700">代码编辑</h2>
      <span v-if="store.activeFile" class="text-xs text-gray-400 font-mono">
        {{ store.activeFile }}
        <span v-if="store.activeFileEntry?.source === 'ai'" class="text-blue-400">(AI 生成)</span>
        <span v-else class="text-green-400">(手动)</span>
      </span>
    </div>
    <FileTabBar
      :files="store.fileList"
      :active-file="store.activeFile"
      @select="store.setActiveFile"
      @close="handleFileClose"
      @add="handleFileAdd"
    />
    <div
      ref="editorContainer"
      class="flex-1"
      @keydown="handleKeydown"
    />
    <div v-if="!store.activeFile" class="flex-1 flex items-center justify-center text-gray-400 text-sm">
      暂无文件 — 通过 AI 对话生成代码，或点击 + 新建
    </div>
  </div>
</template>
```

- [ ] **Step 2: Commit**

```bash
git add src/components/CodeEditor.vue
git commit -m "feat(ai-generation): add CodeEditor component"
```

---

## Task 17: PreviewFrame 组件

**Files:**
- Create: `src/components/PreviewFrame.vue`

- [ ] **Step 1: 实现 PreviewFrame**

```vue
<!-- src/components/PreviewFrame.vue -->
<script setup lang="ts">
import { usePreviewRenderer } from '@/composables/usePreviewRenderer'
import { useMultiCompiler } from '@/composables/useMultiCompiler'

const { iframeRef, iframeReady, errorMessage, refresh } = usePreviewRenderer()
const { isCompiling } = useMultiCompiler()
</script>

<template>
  <div class="preview-frame flex flex-col h-full bg-white">
    <div class="px-4 py-2 border-b border-gray-200 bg-gray-50 flex items-center justify-between">
      <h2 class="text-sm font-semibold text-gray-700">实时预览</h2>
      <div class="flex items-center gap-2">
        <span v-if="isCompiling" class="text-xs px-2 py-0.5 rounded-full bg-yellow-100 text-yellow-700">
          编译中...
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
      <div v-if="!iframeReady" class="absolute inset-0 flex items-center justify-center text-gray-400 text-sm">
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
```

- [ ] **Step 2: Commit**

```bash
git add src/components/PreviewFrame.vue
git commit -m "feat(ai-generation): add PreviewFrame component"
```

---

## Task 18: 整合 GenerationView + 路由 + App.vue

**Files:**
- Create: `src/views/GenerationView.vue`
- Modify: `src/router/index.ts`
- Modify: `src/App.vue`

- [ ] **Step 1: 实现 GenerationView**

```vue
<!-- src/views/GenerationView.vue -->
<script setup lang="ts">
import { onMounted } from 'vue'
import { useGenerationStore } from '@/stores/generation'
import { useCodeParser } from '@/composables/useCodeParser'
import ChatPanel from '@/components/ChatPanel.vue'
import CodeEditor from '@/components/CodeEditor.vue'
import PreviewFrame from '@/components/PreviewFrame.vue'

const store = useGenerationStore()
// 启动 composable 的 watcher
useCodeParser()

onMounted(() => {
  store.resetAll()
})
</script>

<template>
  <div class="generation-view flex h-[calc(100vh-80px)]">
    <!-- 左侧：聊天面板 30% -->
    <div class="w-[30%] min-w-[300px] border-r border-gray-200">
      <ChatPanel />
    </div>

    <!-- 中间：代码编辑 35% -->
    <div class="w-[35%] min-w-[350px] border-r border-gray-200">
      <CodeEditor />
    </div>

    <!-- 右侧：预览 35% -->
    <div class="flex-1 min-w-[350px]">
      <PreviewFrame />
    </div>
  </div>
</template>
```

- [ ] **Step 2: 修改路由**

Edit `src/router/index.ts` — 替换整个文件：

```typescript
import type { RouteRecordRaw } from 'vue-router'
import GenerationView from '../views/GenerationView.vue'

export const routes: RouteRecordRaw[] = [
  { path: '/', name: 'Generation', component: GenerationView },
]
```

- [ ] **Step 3: 简化 App.vue**

Edit `src/App.vue` — 替换 `<template>` 部分：

```vue
<template>
  <div class="ai-generation-app">
    <header class="flex items-center justify-between px-6 py-3 bg-gray-900 text-white">
      <h1 class="text-lg font-bold">AI 代码生成</h1>
      <span class="text-xs text-gray-400">Vue SFC + 实时预览</span>
    </header>
    <router-view />
  </div>
</template>

<script setup lang="ts">
import { onGlobalStateChange } from '@ai-design/micro-core'
onGlobalStateChange((state, prev) => {
  console.log('[ai-generation-app] global state changed:', state, prev)
})
</script>

<style>
/* reset 防基座样式污染 */
.ai-generation-app {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}
.ai-generation-app *,
.ai-generation-app *::before,
.ai-generation-app *::after {
  box-sizing: border-box;
}
</style>
```

- [ ] **Step 4: Commit**

```bash
git add src/views/GenerationView.vue src/router/index.ts src/App.vue
git rm src/views/Home.vue 2>/dev/null || true
git commit -m "feat(ai-generation): integrate GenerationView, update router and App.vue"
```

---

## Task 19: 样式文件

**Files:**
- Create: `src/styles/generation.css`

- [ ] **Step 1: 创建样式**

```css
/* src/styles/generation.css */

/* 三栏布局 */
.generation-view {
  min-height: 0;
}

/* 消息内容中的 Markdown */
.message-content h1,
.message-content h2,
.message-content h3 {
  font-weight: 600;
  margin: 0.5em 0 0.25em;
}
.message-content h1 { font-size: 1.125rem; }
.message-content h2 { font-size: 1rem; }
.message-content h3 { font-size: 0.875rem; }
.message-content p { margin: 0.25em 0; }
.message-content code {
  background: rgba(0,0,0,0.06);
  padding: 1px 4px;
  border-radius: 3px;
  font-size: 0.85em;
}
.message-content pre {
  background: #1e1e1e;
  color: #d4d4d4;
  padding: 8px 12px;
  border-radius: 6px;
  overflow-x: auto;
  font-size: 0.8em;
  margin: 0.5em 0;
}

/* ChatPanel 消息滚动 */
.chat-panel .overflow-y-auto {
  scroll-behavior: smooth;
}

/* Monaco 覆写 */
.code-editor .monaco-editor {
  position: absolute !important;
  top: 0;
  left: 0;
}

/* FileTabBar 滚动 */
.file-tab-bar::-webkit-scrollbar {
  height: 2px;
}
.file-tab-bar::-webkit-scrollbar-thumb {
  background: #cbd5e1;
  border-radius: 2px;
}
```

- [ ] **Step 2: 在 main.ts 中导入样式**

Edit `src/main.ts` — 在 `import './styles/global.css'` 后添加：

```typescript
import './styles/generation.css'
```

- [ ] **Step 3: Commit**

```bash
git add src/styles/generation.css src/main.ts
git commit -m "feat(ai-generation): add generation styles"
```

---

## Task 20: 配置 Monaco Webpack 插件

**Files:**
- Modify: `webpack/webpack.common.js`

- [ ] **Step 1: 添加 MonacoWebpackPlugin**

Edit `webpack/webpack.common.js` — 在顶部 require 区添加：

```javascript
const MonacoWebpackPlugin = require('monaco-editor-webpack-plugin');
```

在 plugins 数组中添加：

```javascript
new MonacoWebpackPlugin({
  languages: ['html', 'css', 'javascript', 'typescript'],
  features: ['bracketMatching', 'wordHighlighter', 'find', 'folding', 'lineSelection'],
}),
```

完整修改后 plugins 数组应为：

```javascript
plugins: [
  new VueLoaderPlugin(),
  new HtmlWebpackPlugin({
    template: path.resolve(__dirname, '../public/index.html'),
    title: 'AI Generation',
  }),
  new MonacoWebpackPlugin({
    languages: ['html', 'css', 'javascript', 'typescript'],
    features: ['bracketMatching', 'wordHighlighter', 'find', 'folding', 'lineSelection'],
  }),
  ...(isDev ? [] : [new MiniCssExtractPlugin({ filename: 'css/[name].[contenthash:8].css' })]),
],
```

- [ ] **Step 2: Commit**

```bash
git add webpack/webpack.common.js
git commit -m "chore(ai-generation): add MonacoWebpackPlugin config"
```

---

## Task 21: 端到端验证

- [ ] **Step 1: 启动开发服务器**

```bash
cd ai-design-platform/ai-design-platform-web/packages/ai-generation-app
pnpm dev
```

Expected: webpack-dev-server 启动在 `http://localhost:8002`，无编译错误

- [ ] **Step 2: 验证 UI 渲染**

打开 `http://localhost:8002`，验证：
- 三栏布局正常显示（ChatPanel | CodeEditor | PreviewFrame）
- 头部导航显示 "AI 代码生成"
- 聊天区显示欢迎文案
- 组件库选择器有 4 个选项（Tailwind / AntDV / Element+ / ECharts）

- [ ] **Step 3: 验证流式聊天**

1. 输入框输入 "创建一个简单的计数器组件"
2. 点击发送
3. 验证：用户消息出现在聊天区，AI 消息开始流式输出
4. 如果后端未启动，验证错误提示正确展示

- [ ] **Step 4: 验证代码编辑**

1. 确认 Monaco 编辑器正常渲染
2. 确认 TabBar 功能正常
3. 手动输入代码验证高亮和补全

- [ ] **Step 5: 验证编译与预览**

1. 使用已安装的依赖验证 `compileSFC` 可正常编译简单组件
2. 验证 iframe 渲染正常

- [ ] **Step 6: 运行所有单元测试**

```bash
pnpm test
```

Expected: 所有 utils 测试 PASS

- [ ] **Step 7: 验证完成**

确认所有功能点：
- [x] 三栏布局
- [x] 组件库选择
- [x] AI 流式对话
- [x] 代码块检测与解析
- [x] 多文件 Tab 管理
- [x] Monaco 代码编辑
- [x] SFC 编译（@vue/repl）
- [x] iframe 沙箱渲染
- [x] 安全扫描
- [x] 编译错误展示
