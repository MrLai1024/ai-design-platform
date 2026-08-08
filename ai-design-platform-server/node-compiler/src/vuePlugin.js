// src/vuePlugin.js
// esbuild plugin: resolve project files (relative paths, `@/` alias, extension
// completion) from the in-memory file map, and compile .vue SFCs via
// vue/compiler-sfc — mirrors the frontend bundler's resolution rules so
// server-side validation matches what the preview actually builds.
import { parse, compileScript, compileTemplate, compileStyle } from '@vue/compiler-sfc'
import { dirname, join, normalize, sep } from 'node:path'

function hash(str) {
  let h = 0
  for (let i = 0; i < str.length; i++) {
    h = ((h << 5) - h + str.charCodeAt(i)) | 0
  }
  return Math.abs(h).toString(36).slice(0, 8)
}

/** Extension candidates for import completion (same order as the frontend). */
const EXT_CANDIDATES = ['', '.vue', '.ts', '.js']

/** Normalize a project-relative path (posix, no leading ./). */
function norm(p) {
  return normalize(p).replace(/\\/g, '/').replace(/^\.\//, '')
}

/**
 * Candidate project paths for an import specifier.
 * - `@/x` → `src/x`
 * - relative (`./x`, `../x`) → resolved against the importer's directory
 * - otherwise bare specifiers are left to esbuild (externals like `vue`)
 * Each candidate is tried as-is and with extension completion.
 */
function resolveCandidates(specifier, importer, files) {
  const candidates = []
  let base
  if (specifier.startsWith('@/')) {
    base = 'src/' + specifier.slice(2)
  } else if (specifier.startsWith('./') || specifier.startsWith('../')) {
    base = norm(join(dirname(importer), specifier))
  } else {
    return [] // bare import (vue / vue-router / pinia) — let esbuild handle
  }

  for (const ext of EXT_CANDIDATES) {
    candidates.push(base + ext)
    candidates.push(norm(join(base, 'index' + ext)))
  }
  return candidates.filter((c, i) => candidates.indexOf(c) === i)
}

export function createVuePlugin({ files, cssChunks, projectRoot = '' }) {
  /** Relativize an absolute importer path against the project root.
   *  Both sides normalized to posix (forward slashes) before comparing. */
  function relImporter(importer) {
    if (!importer) return ''
    const normImporter = norm(importer)
    const normRoot = norm(projectRoot)
    if (normRoot && normImporter.startsWith(normRoot)) {
      return normImporter.slice(normRoot.length).replace(/^[/]/, '')
    }
    return normImporter
  }

  return {
    name: 'compile-vue',
    setup(build) {
      build.onResolve({ filter: /.*/ }, (args) => {
        // Entry point (importer='') — let esbuild resolve from absWorkingDir.
        if (!args.importer) return null
        // Bare imports (vue / vue-router / pinia) — external.
        if (!/^[./@]/.test(args.path)) return null

        for (const cand of resolveCandidates(args.path, relImporter(args.importer), files)) {
          if (files[cand] !== undefined) {
            // .vue → compile via vue-sfc namespace; .ts/.js exist on disk, so
            // let esbuild's default resolution handle them (relative path in
            // the "file" namespace would be rejected).
            if (cand.endsWith('.vue')) {
              return { path: cand, namespace: 'vue-sfc' }
            }
            return null
          }
        }
        // Explicit .vue specifier that doesn't exist → "Could not resolve"
        // phrasing so the partial detector (dependency not generated yet)
        // treats it like any other unresolved import during quick checks.
        if (/\.vue$/.test(args.path)) {
          return { errors: [{ text: `Could not resolve "${args.path}"` }] }
        }
        return null // fall through to esbuild default resolution
      })

      build.onLoad({ filter: /\.vue$/, namespace: 'vue-sfc' }, (args) => {
        const source = files[args.path]
        if (source === undefined) {
          return { errors: [{ text: `File not found: ${args.path}` }] }
        }

        const id = hash(args.path)
        const { descriptor, errors } = parse(source, { filename: args.path })
        if (errors.length) {
          return {
            errors: errors.map((e) => ({ text: typeof e === 'string' ? e : e.message })),
          }
        }

        const hasScoped = descriptor.styles.some((s) => s.scoped)
        const scopeId = hasScoped ? `data-v-${id}` : null

        // ── 样式：编译后收集，不进 bundle ──
        for (const style of descriptor.styles) {
          const result = compileStyle({ source: style.content, filename: args.path, id, scoped: style.scoped })
          if (result.code) cssChunks.push(`/* ${args.path} */\n${result.code}`)
        }

        let js
        if (descriptor.script || descriptor.scriptSetup) {
          const compiled = compileScript(descriptor, {
            id,
            inlineTemplate: true,
            templateOptions: { compilerOptions: {} },
          })
          js = compiled.content
          if (hasScoped && scopeId) {
            js += `\n;import { getCurrentInstance as __getCI } from 'vue'`
            js = js.replace(
              /export default (\w+)/,
              (m, name) => `${name}.__scopeId = ${JSON.stringify(scopeId)};\nexport default ${name}`,
            )
          }
        } else if (descriptor.template) {
          const compiled = compileTemplate({ source: descriptor.template.content, filename: args.path, id, compilerOptions: {} })
          js = [
            compiled.code,
            `const __sfc_component__ = { render }`,
            scopeId ? `__sfc_component__.__scopeId = ${JSON.stringify(scopeId)}` : '',
            `export default __sfc_component__`,
          ].filter(Boolean).join('\n')
        } else {
          js = 'export default {}'
        }

        return { contents: js, loader: 'ts' }
      })
    },
  }
}
