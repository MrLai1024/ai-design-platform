// src/compile.js
// Real compilation for generated Vue projects: esbuild bundle check (syntax,
// imports, SFC compile) + optional vue-tsc --noEmit type check.
import { build } from 'esbuild'
import { createRequire } from 'node:module'
import { dirname, join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'
import { existsSync, readFileSync, writeFileSync, unlinkSync, readdirSync, statSync } from 'node:fs'
import { createVuePlugin } from './vuePlugin.js'

const require = createRequire(import.meta.url)

// Third-party packages the generated project relies on but never ships
// node_modules for — resolved via the frontend preview's CDN import map.
// esbuild marks them external; vue-tsc resolves them via shims.
const EXTERNAL = ['vue', 'vue-router', 'pinia', 'element-plus', '@element-plus/icons-vue']

/** Collect all project files as {relPath: content} (skip dot-dirs like .ai-memory). */
export function collectFiles(projectRoot) {
  const files = {}
  function walk(dir) {
    for (const name of readdirSync(dir)) {
      if (name.startsWith('.')) continue
      const full = join(dir, name)
      const st = statSync(full)
      if (st.isDirectory()) {
        walk(full)
      } else if (st.isFile()) {
        try {
          files[relative(projectRoot, full).replace(/\\/g, '/')] = readFileSync(full, 'utf-8')
        } catch {
          /* binary/undecodable — skip */
        }
      }
    }
  }
  walk(projectRoot)
  return files
}

const PARTIAL_RE = /Could not resolve/
// Unresolved paths ride along so the caller can check whether they're planned
// by any task (if not → planning gap → incremental replan).
const RESOLVE_PATH_RE = /["']([^"']+)["']/


function isPartialErrors(errors) {
  return errors.length > 0 && errors.every((e) => PARTIAL_RE.test(e.message))
}

function partialPaths(errors) {
  const paths = []
  for (const e of errors) {
    const m = RESOLVE_PATH_RE.exec(e.message || '')
    if (m) {
      const raw = m[1]
      // Project specifiers (./x, ../x, @/x → src/) are planning-gap signals.
      // Bare package specifiers (@element-plus/icons-vue, vue) are infra —
      // handled by external/stubs, never replanned.
      let p
      if (raw.startsWith('@/')) p = 'src/' + raw.slice(2)
      else if (raw.startsWith('./') || raw.startsWith('../')) p = raw.replace(/^\.\//, '')
      else continue
      if (p && !paths.includes(p)) paths.push(p)
    }
  }
  return paths
}

/**
 * Compile a generated project.
 * @param {string} projectRoot
 * @param {{full?: boolean, entry?: string}} [opts]
 * @returns {Promise<{ok: boolean, errors: Array<{file: string, line: number, column: number, message: string, source: string}>, partial?: boolean}>}
 */
export async function compileProject(projectRoot, opts = {}) {
  const { full = false, entry } = opts
  const errors = []

  // ── 1. esbuild bundle check ──
  if (!existsSync(projectRoot)) {
    return {
      ok: false,
      errors: [{ file: '', line: 0, column: 0, message: `项目目录不存在：${projectRoot}`, source: 'node-compiler' }],
    }
  }
  const esbuildErrors = await esbuildCheck(projectRoot, entry)
  errors.push(...esbuildErrors)

  // Partial: every error is "Could not resolve" — dependencies not generated
  // yet (executor generates files incrementally; the entry may import files
  // from a later task). Only tolerated on quick checks (full=false): the
  // executor keeps generating. On the FINAL compile (full=true) dependencies
  // should all exist — a remaining "Could not resolve" is a real defect and
  // must surface (vue-tsc Cannot find module backs this up).
  if (!full && isPartialErrors(errors)) {
    return { ok: false, errors: [], partial: true, partial_paths: partialPaths(errors) }
  }

  // ── 2. vue-tsc type check (full mode only) ──
  if (full) {
    const typeErrors = await vueTscCheck(projectRoot)
    errors.push(...typeErrors)
  }

  return { ok: errors.length === 0, errors }
}

async function esbuildCheck(projectRoot, entry) {
  const files = collectFiles(projectRoot)
  if (Object.keys(files).length === 0) {
    return [{ file: '', line: 0, column: 0, message: '项目目录为空，无文件可编译', source: 'node-compiler' }]
  }

  const resolvedEntry = entry ?? (files['src/main.ts'] ? 'src/main.ts' : files['App.vue'] ? 'App.vue' : null)
  if (!resolvedEntry) {
    return [{
      file: '', line: 0, column: 0,
      message: `未找到入口文件（需要 src/main.ts 或 App.vue）。实际文件: ${Object.keys(files).slice(0, 10).join(', ')}`,
      source: 'node-compiler',
    }]
  }

  const cssChunks = []
  const options = {
    entryPoints: [resolvedEntry],
    bundle: true,
    write: false,
    format: 'esm',
    target: 'es2020',
    logLevel: 'silent',
    outdir: 'out',
    external: EXTERNAL,
    absWorkingDir: projectRoot,
    plugins: [createVuePlugin({ files, cssChunks, projectRoot })],
  }

  try {
    const result = await build(options)
    return result.errors.map(toCompileError)
  } catch (e) {
    const msgs = e?.errors?.length ? e.errors : [{ text: String(e?.message ?? e) }]
    return msgs.map(toCompileError)
  }
}

async function vueTscCheck(projectRoot) {
  // Write a temporary tsconfig into the project (doesn't modify source files).
  // vue/vue-router/pinia resolve to the worker's own type stubs — the
  // generated project has no node_modules of its own.
  const shimDir = join(dirname(fileURLToPath(import.meta.url)), 'shims')
  const tsconfig = {
    compilerOptions: {
      target: 'ES2020',
      module: 'ESNext',
      moduleResolution: 'bundler',
      strict: false,
      jsx: 'preserve',
      resolveJsonModule: true,
      esModuleInterop: true,
      skipLibCheck: true,
      allowJs: true,
      noEmit: true,
      paths: {
        '@/*': ['./src/*'],
        // REAL framework types from node-compiler's own node_modules — the
        // hand-written stubs were too thin: template bindings collapsed to
        // '{}' (TS2339) and named type imports failed (TS2614). Real types
        // make vue-tsc's script-setup/template checking work correctly.
        'vue': [join(dirname(require.resolve('vue/package.json')), 'dist/vue.d.ts')],
        'vue-router': [join(dirname(require.resolve('vue-router/package.json')), 'dist/vue-router.d.mts')],
        'pinia': [join(dirname(require.resolve('pinia/package.json')), 'dist/pinia.d.ts')],
        // element-plus is heavy — keep a stub (template tags need no types)
        'element-plus': [join(shimDir, 'element-plus.d.ts')],
        // Real icons package types (dist/types/index.d.ts) — any icon imports
        // resolve; the package itself is small and dependency-free.
        '@element-plus/icons-vue': [join(dirname(require.resolve('@element-plus/icons-vue/package.json')), 'dist/types/index.d.ts')],
      },
    },
    include: ['src/**/*.ts', 'src/**/*.vue'],
  }
  const configPath = join(projectRoot, 'tsconfig.compile.json')
  writeFileSync(configPath, JSON.stringify(tsconfig, null, 2))
  try {
    const { execFile } = await import('node:child_process')
    const { promisify } = await import('node:util')
    const execFileAsync = promisify(execFile)
    const vueTscBin = require.resolve('vue-tsc/bin/vue-tsc.js')
    const { stdout, stderr } = await execFileAsync(process.execPath, [vueTscBin, '--noEmit', '-p', configPath], {
      cwd: projectRoot,
      maxBuffer: 16 * 1024 * 1024,
    })
    if (stderr && !stdout) return parseVueTscOutput(stderr, projectRoot)
    return [] // exit 0 → no type errors
  } catch (e) {
    // vue-tsc exits non-zero on type errors; stdout carries the diagnostics.
    const out = e?.stdout || e?.stderr || ''
    return parseVueTscOutput(out, projectRoot)
  } finally {
    try { unlinkSync(configPath) } catch { /* ignore */ }
  }
}

function parseVueTscOutput(output, projectRoot) {
  const errors = []
  const re = /([^\s].*?)\((\d+),(\d+)\):\s+error\s+(TS\d+):\s+(.+)/g
  let m
  while ((m = re.exec(output)) !== null) {
    const [, file, line, col, code, message] = m
    // vue-tsc prints paths relative to cwd (= projectRoot); only relativize
    // absolute paths (path.relative would resolve relative input against
    // THIS process's cwd — a different dir — producing wrong absolutes).
    const isAbsolute = /^[A-Za-z]:[\\/]|^[/]/.test(file)
    const rel = isAbsolute ? relative(projectRoot, file).replace(/\\/g, '/') : file.replace(/\\/g, '/')
    errors.push({
      file: rel.startsWith('..') ? file : rel,
      line: Number(line),
      column: Number(col),
      message: `[${code}] ${message}`,
      source: 'vue-tsc',
    })
  }
  return errors
}

function toCompileError(msg) {
  return {
    file: msg.location?.file ?? '',
    line: msg.location?.line ?? 0,
    column: msg.location?.column ?? 0,
    message: msg.text,
    source: 'esbuild',
  }
}
