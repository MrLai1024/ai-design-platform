// src/utils/buildPreviewHtml.test.ts
import { describe, it, expect } from 'vitest'
import { buildPreviewHtml } from '../src/utils/buildPreviewHtml'

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
    // Only the Vue runtime script should be present, no additional CDN script tags
    const scriptSrcCount = (html.match(/<script src=/g) || []).length
    expect(scriptSrcCount).toBe(1)
  })
})
