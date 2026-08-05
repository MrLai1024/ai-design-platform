// src/composables/useRuntimeFeedback.test.ts
// 5.4 L3: iframe 运行时错误 → 批量上报 /api/v1/generation/runtime-feedback。
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => {
  return {
    generationId: null as string | null,
    fetchMock: vi.fn(),
  }
})

vi.mock('@/stores/generation', () => ({
  useGenerationStore: () => ({
    get currentGenerationId() {
      return mocks.generationId
    },
  }),
}))

import { RUNTIME_CAPTURE_SCRIPT, buildPreviewDoc } from '@/bundler/previewTemplate'
import { useRuntimeFeedback } from './useRuntimeFeedback'

describe('useRuntimeFeedback', () => {
  beforeEach(() => {
    mocks.generationId = 'gen-5b-1'
    mocks.fetchMock.mockReset()
    mocks.fetchMock.mockResolvedValue({ ok: true })
    vi.stubGlobal('fetch', mocks.fetchMock)
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('buffers captured errors and flushes as a batch POST', async () => {
    const fb = useRuntimeFeedback()
    fb.capture([{ type: 'console_error', message: 'boom' }])
    fb.capture([{ type: 'uncaught', message: 'x', stack: 'at f (a.vue:1)' }])
    expect(fb.buffer.value.length).toBe(2)

    await vi.advanceTimersByTimeAsync(2100)
    expect(mocks.fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = mocks.fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/v1/generation/runtime-feedback')
    const body = JSON.parse(String(init.body))
    expect(body.generation_id).toBe('gen-5b-1')
    expect(body.errors).toEqual([
      { type: 'console_error', message: 'boom' },
      { type: 'uncaught', message: 'x', stack: 'at f (a.vue:1)' },
    ])
    expect(fb.buffer.value.length).toBe(0)
  })

  it('normalizes error fields and caps lengths', () => {
    const fb = useRuntimeFeedback()
    fb.capture([{ type: 'network', message: 'x'.repeat(600), url: 'http://u' }])
    expect(fb.buffer.value[0]!.message.length).toBe(500)
    expect(fb.buffer.value[0]!.type).toBe('network')
  })

  it('does not POST when no generation id is set', async () => {
    mocks.generationId = null
    const fb = useRuntimeFeedback()
    fb.capture([{ type: 'uncaught', message: 'orphan' }])
    await vi.advanceTimersByTimeAsync(2100)
    expect(mocks.fetchMock).not.toHaveBeenCalled()
    // 缓冲被清空（新构建 clear 也走同样逻辑），不会残留
    expect(fb.buffer.value.length).toBe(0)
  })

  it('clear() drops the local buffer and posts an empty batch', async () => {
    const fb = useRuntimeFeedback()
    fb.capture([{ type: 'console_error', message: 'stale' }])
    fb.clear()
    expect(fb.buffer.value.length).toBe(0)
    expect(mocks.fetchMock).toHaveBeenCalledTimes(1)
    const [, init] = mocks.fetchMock.mock.calls[0] as [string, RequestInit]
    const body = JSON.parse(String(init.body))
    expect(body.errors).toEqual([])
  })

  it('flush() is a no-op when buffer is empty', async () => {
    const fb = useRuntimeFeedback()
    expect(await fb.flush()).toBe(false)
    expect(mocks.fetchMock).not.toHaveBeenCalled()
  })

  it('compensates with an empty batch when clear() lands during an in-flight flush', async () => {
    // Review fix (Important): 旧构建的 flush POST 在 clear() 之后才落地 →
    // 落地成功后检测 epoch 变化 → 补发空批次，防止 stale 错误覆盖新构建清空。
    const fb = useRuntimeFeedback()
    const resolvers: Array<(v: Response) => void> = []
    mocks.fetchMock.mockImplementation(
      () => new Promise((res) => { resolvers.push(res) }),
    )

    fb.capture([{ type: 'console_error', message: 'stale' }])
    const flushPromise = fb.flush()   // POST #1: 旧构建批次，在途
    fb.clear()                         // epoch 递增 + POST #2: 空批次
    expect(mocks.fetchMock).toHaveBeenCalledTimes(2)

    // 旧批次在 clear 之后落地（成功）→ 触发补偿空批次 POST #3
    resolvers[0]!({ ok: true } as Response)
    await flushPromise
    await Promise.resolve()
    expect(mocks.fetchMock).toHaveBeenCalledTimes(3)

    resolvers[1]!({ ok: true } as Response)   // clear 自己的空批次
    await Promise.resolve()
    resolvers[2]!({ ok: true } as Response)   // 补偿空批次
    await Promise.resolve()

    const bodies = mocks.fetchMock.mock.calls.map((c) => JSON.parse(String((c[1] as RequestInit).body)))
    expect(bodies).toEqual([
      { generation_id: 'gen-5b-1', errors: [{ type: 'console_error', message: 'stale' }] },
      { generation_id: 'gen-5b-1', errors: [] },
      { generation_id: 'gen-5b-1', errors: [] },
    ])
  })

  it('does not compensate when no clear happened mid-flight', async () => {
    const fb = useRuntimeFeedback()
    fb.capture([{ type: 'uncaught', message: 'ok' }])
    await vi.advanceTimersByTimeAsync(2100)
    expect(mocks.fetchMock).toHaveBeenCalledTimes(1)
  })
})

describe('RUNTIME_CAPTURE_SCRIPT (预览 iframe 捕获注入)', () => {
  it('wraps console.error, error, unhandledrejection, fetch and XHR', () => {
    expect(RUNTIME_CAPTURE_SCRIPT).toContain('console.error')
    expect(RUNTIME_CAPTURE_SCRIPT).toContain('addEventListener(\'error\'')
    expect(RUNTIME_CAPTURE_SCRIPT).toContain('unhandledrejection')
    expect(RUNTIME_CAPTURE_SCRIPT).toContain('window.fetch')
    expect(RUNTIME_CAPTURE_SCRIPT).toContain('XMLHttpRequest.prototype.open')
    expect(RUNTIME_CAPTURE_SCRIPT).toContain('runtime-error')
    // Review fix (Minor): abort 是用户主动取消，不算应用错误 —— 不上报
    expect(RUNTIME_CAPTURE_SCRIPT).not.toContain('xhr aborted')
  })

  it('is embedded in the preview doc before the module bundle', () => {
    const doc = buildPreviewDoc({ js: 'console.log(1)', css: '' })
    const scriptIdx = doc.indexOf(RUNTIME_CAPTURE_SCRIPT)
    expect(scriptIdx).toBeGreaterThan(-1)
    // 捕获脚本在 <script type="module"> 之前执行（错误尽早开始记录）
    expect(doc.indexOf('type="module"')).toBeGreaterThan(scriptIdx)
    // 模板转义没破坏捕获脚本
    expect(doc).toContain('window.__aiRuntimeCaptureInstalled')
  })
})
