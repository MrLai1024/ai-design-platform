// src/utils/securityScan.test.ts
import { describe, it, expect } from 'vitest'
import { scanCode } from '../src/utils/securityScan'

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
