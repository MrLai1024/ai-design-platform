// src/composables/useE2ERunner.test.ts
// 6.3/6.7: 执行引擎升级 —— 等待条件（轮询替代固定 sleep）、证据收集
// （DOM 快照 + console/网络 postMessage 通道）、requires_browser 跳过。
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ref, type Ref } from 'vue'
import {
  documentContainsText,
  resolveElement,
  startEvidenceCollector,
  useE2ERunner,
  waitForElement,
  SKIPPED_REQUIRES_BROWSER,
  type E2ETestCase,
} from './useE2ERunner'

function makeDoc(html: string): Document {
  const doc = document.implementation.createHTMLDocument('preview')
  doc.body.innerHTML = html
  return doc
}

function makeCase(overrides: Partial<E2ETestCase> = {}): E2ETestCase {
  return {
    id: 'tc-r01-1',
    requirement_id: 'R-01',
    scenario: '分页切换',
    steps: [
      { action: 'click', target: { by: 'testid', value: 'pagination-next' } },
      { action: 'assert', target: { by: 'text', value: '第 2 页' }, assertion: 'contains' },
    ],
    requires_browser: false,
    ...overrides,
  }
}

describe('resolveElement', () => {
  it('resolves testid / role / css selectors', () => {
    const doc = makeDoc(`
      <button data-testid="save-button">保存</button>
      <nav role="pagination"><span>1</span></nav>
      <div id="panel">panel</div>
    `)
    expect(resolveElement(doc, { by: 'testid', value: 'save-button' })?.textContent).toBe('保存')
    expect(resolveElement(doc, { by: 'role', value: 'pagination' })?.tagName).toBe('NAV')
    expect(resolveElement(doc, { by: 'css', value: '#panel' })?.textContent).toBe('panel')
    expect(resolveElement(doc, { by: 'testid', value: 'missing' })).toBeNull()
  })

  it('resolves text by exact leaf-text match', () => {
    const doc = makeDoc('<div><button>下一页</button><span>第 2 页</span></div>')
    const el = resolveElement(doc, { by: 'text', value: '第 2 页' })
    expect(el?.tagName).toBe('SPAN')
    expect(resolveElement(doc, { by: 'text', value: '不存在' })).toBeNull()
  })
})

describe('documentContainsText', () => {
  it('finds text anywhere in the page', () => {
    const doc = makeDoc('<div><span>第 2 页</span></div>')
    expect(documentContainsText(doc, '第 2 页')).toBe(true)
    expect(documentContainsText(doc, '第 3 页')).toBe(false)
  })
})

describe('waitForElement (6.3 等待条件)', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('resolves immediately when the element exists', async () => {
    const doc = makeDoc('<button data-testid="save-button">保存</button>')
    const el = await waitForElement(doc, { by: 'testid', value: 'save-button' }, 1000)
    expect(el).not.toBeNull()
  })

  it('polls until the element appears (MutationObserver + 轮询)', async () => {
    const doc = makeDoc('<div id="root"></div>')
    const promise = waitForElement(doc, { by: 'testid', value: 'late-button' }, 2000)
    let resolved: HTMLElement | null | undefined
    promise.then((el) => { resolved = el })

    // element appears after 300ms
    setTimeout(() => {
      const btn = doc.createElement('button')
      btn.setAttribute('data-testid', 'late-button')
      doc.getElementById('root')!.appendChild(btn)
    }, 300)

    await vi.advanceTimersByTimeAsync(500)
    expect(resolved).not.toBeNull()
  })

  it('resolves null on timeout instead of sleeping a fixed amount', async () => {
    const doc = makeDoc('<div></div>')
    const promise = waitForElement(doc, { by: 'testid', value: 'never' }, 300)
    let resolved: HTMLElement | null | undefined
    promise.then((el) => { resolved = el })
    await vi.advanceTimersByTimeAsync(400)
    expect(resolved).toBeNull()
  })
})

describe('useE2ERunner', () => {
  let iframeRef: Ref<HTMLIFrameElement | null>

  function stubPreview(html: string): Document {
    const doc = makeDoc(html)
    const iframe = document.createElement('iframe') as HTMLIFrameElement
    Object.defineProperty(iframe, 'contentDocument', { value: doc })
    // M8: 证据收集器校验 ev.source === iframe.contentWindow
    Object.defineProperty(iframe, 'contentWindow', { value: {} })
    iframeRef.value = iframe
    return doc
  }

  /** 模拟捕获脚本：从 iframe 窗口（ev.source = contentWindow）postMessage */
  function postFromPreview(data: unknown): void {
    const source = (iframeRef.value?.contentWindow ?? null) as MessageEventSource | null
    window.dispatchEvent(new MessageEvent('message', { data, source }))
  }

  beforeEach(() => {
    iframeRef = ref<HTMLIFrameElement | null>(null)
    vi.stubGlobal('MutationObserver', undefined)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('runs a passing DSL case (click + assert)', async () => {
    stubPreview('<button data-testid="pagination-next">下一页</button><span>第 2 页</span>')
    const { executeCase } = useE2ERunner(iframeRef)
    const result = await executeCase(makeCase())
    expect(result.passed).toBe(true)
    expect(result.status).toBe('passed')
  })

  it('collects evidence (DOM snapshot + console/network errors) on failure', async () => {
    const doc = stubPreview('<button data-testid="pagination-next">下一页</button>')
    const { executeCase } = useE2ERunner(iframeRef)
    const runPromise = executeCase(makeCase()) // assert 第 2 页 fails

    // simulate the capture script's postMessage channel during the case
    postFromPreview({ type: 'runtime-error', errors: [
      { type: 'console_error', message: 'boom: Cannot read properties' },
      { type: 'network', message: 'fetch failed', url: '/api/list' },
    ] })

    const result = await runPromise
    expect(result.passed).toBe(false)
    expect(result.status).toBe('failed')
    expect(result.error).toContain('第 2 页')
    expect(result.evidence?.dom_snapshot).toContain('pagination-next')
    expect(result.evidence?.console_errors.some((e) => e.includes('boom'))).toBe(true)
    expect(result.evidence?.network_errors.some((e) => e.includes('/api/list'))).toBe(true)
    expect(result.evidence?.screenshot_note).toContain('html2canvas')
  })

  it('ignores messages from other windows (M8 source check)', async () => {
    stubPreview('<button data-testid="pagination-next">下一页</button><span>第 2 页</span>')
    const { executeCase } = useE2ERunner(iframeRef)
    const runPromise = executeCase(makeCase())
    // 来自其它窗口（source = window 本身）的消息被过滤
    window.dispatchEvent(new MessageEvent('message', {
      data: { type: 'runtime-error', errors: [{ type: 'console_error', message: 'noise' }] },
      source: window,
    }))
    const result = await runPromise
    expect(result.passed).toBe(true)
    expect(result.evidence?.console_errors.some((e) => e.includes('noise'))).toBe(false)
  })

  it('captures the legacy err postMessage channel as console evidence', async () => {
    // click 步骤内含 await（50ms）—— 在该窗口内触发 postMessage，证据收集器仍活跃
    stubPreview('<button data-testid="pagination-next">下一页</button>')
    const { executeCase } = useE2ERunner(iframeRef)
    const failing = makeCase({
      steps: [
        { action: 'click', target: { by: 'testid', value: 'pagination-next' } },
        { action: 'assert', target: { by: 'text', value: '第 3 页' }, assertion: 'contains' },
      ],
    })
    const runPromise = executeCase(failing)
    setTimeout(() => {
      postFromPreview({ type: 'err', message: 'Async: something failed' })
    }, 0)
    const result = await runPromise
    expect(result.passed).toBe(false)
    expect(result.evidence?.console_errors.some((e) => e.includes('Async'))).toBe(true)
  })

  it('skips requires_browser cases with status skipped_requires_browser (6.7)', async () => {
    stubPreview('<div></div>')
    const { executeCase } = useE2ERunner(iframeRef)
    const result = await executeCase(makeCase({ requires_browser: true }))
    expect(result.passed).toBe(false)
    expect(result.status).toBe(SKIPPED_REQUIRES_BROWSER)
    expect(result.error).toContain('requires_browser')
  })

  it('executeAll skips requires_browser and keeps them in results', async () => {
    stubPreview('<button data-testid="pagination-next">下一页</button><span>第 2 页</span>')
    const { executeAll } = useE2ERunner(iframeRef)
    const cases = [
      makeCase(),
      makeCase({ id: 'tc-r99-1', requirement_id: 'R-99', scenario: '多页面流转', requires_browser: true }),
    ]
    const results = await executeAll(cases, () => {})
    expect(results).toHaveLength(2)
    expect(results[0].passed).toBe(true)
    expect(results[1].status).toBe(SKIPPED_REQUIRES_BROWSER)
  })

  it('fails when the preview iframe is unavailable', async () => {
    const { executeCase } = useE2ERunner(iframeRef)
    const result = await executeCase(makeCase())
    expect(result.passed).toBe(false)
    expect(result.error).toContain('Preview iframe not available')
  })

  it('rejects invalid DSL cases before execution (spec: 非法 DSL 拒绝执行)', async () => {
    stubPreview('<button data-testid="save-button">保存</button>')
    const { executeCase } = useE2ERunner(iframeRef)
    // 非法 DSL：类型系统之外的坏数据（模拟 LLM 脏输出）
    const invalid = makeCase({
      steps: [{ action: 'hover', target: { by: 'xpath', value: '//div' } }] as any,
    })
    const result = await executeCase(invalid)
    expect(result.passed).toBe(false)
    expect(result.error).toContain('非法 DSL 用例，拒绝执行')
    expect(result.error).toContain('action 非法')
    expect(result.error).toContain('target 非法')
  })
})

describe('startEvidenceCollector', () => {
  it('unsubscribes after stop()', () => {
    const iframe = document.createElement('iframe') as HTMLIFrameElement
    Object.defineProperty(iframe, 'contentWindow', { value: {} })
    const collector = startEvidenceCollector(iframe)
    collector.stop()
    window.dispatchEvent(new MessageEvent('message', {
      data: { type: 'runtime-error', errors: [{ type: 'console_error', message: 'x' }] },
      source: iframe.contentWindow,
    }))
    expect(collector.evidence.console_errors).toHaveLength(0)
  })
})
