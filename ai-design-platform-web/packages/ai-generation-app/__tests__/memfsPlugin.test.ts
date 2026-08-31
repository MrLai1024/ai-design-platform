// Tests: memfs plugin resolves the ENTRY point.
//
// esbuild-wasm's default resolver cannot read directories ("not implemented
// on js") — entryPoints like "src/main.ts" (no ./ prefix) fell through to it
// and produced:
//   Cannot read directory ".": not implemented on js
//   Cannot read directory "src": not implemented on js
//   Could not resolve "src/main.ts"
// The memfs plugin must take over entry resolution (importer === '').
import { describe, expect, it } from 'vitest'
import { createMemfsPlugin } from '../src/bundler/memfsPlugin'

type Resolver = (args: any) => any

function collectResolvers(files: Map<string, string>): Resolver[] {
  const resolvers: Resolver[] = []
  const build = {
    onResolve: (_opts: any, fn: Resolver) => { resolvers.push(fn) },
    onLoad: () => {},
  }
  createMemfsPlugin({ files, cssChunks: [] }).setup(build as any)
  return resolvers
}

// The entry resolver is the catch-all registered LAST.
function entryResolver(resolvers: Resolver[]): Resolver {
  return resolvers[resolvers.length - 1]!
}

describe('memfs entry resolution', () => {
  it('resolves the src/main.ts entry into the memfs namespace', () => {
    const files = new Map([['src/main.ts', 'import App from "./App.vue"']])
    const resolvers = collectResolvers(files)
    const out = entryResolver(resolvers)({ importer: '', path: 'src/main.ts', resolveDir: '' })
    expect(out).toEqual({ path: 'src/main.ts', namespace: 'memfs' })
  })

  it('resolves a root-level main.ts entry', () => {
    const files = new Map([['main.ts', 'x']])
    const resolvers = collectResolvers(files)
    const out = entryResolver(resolvers)({ importer: '', path: 'main.ts', resolveDir: '' })
    expect(out).toEqual({ path: 'main.ts', namespace: 'memfs' })
  })

  it('ignores non-entry imports (importer present)', () => {
    const files = new Map([['src/main.ts', 'x']])
    const resolvers = collectResolvers(files)
    const out = entryResolver(resolvers)({ importer: 'src/App.vue', path: './main.ts', resolveDir: '' })
    expect(out).toBeNull()
  })

  it('errors on a missing entry instead of hitting the wasm default resolver', () => {
    const files = new Map([['src/api/book.ts', 'x']])
    const resolvers = collectResolvers(files)
    const out = entryResolver(resolvers)({ importer: '', path: 'src/main.ts', resolveDir: '' })
    expect(out.errors).toBeDefined()
    expect(out.errors[0]?.text).toContain('Could not resolve')
  })
})
