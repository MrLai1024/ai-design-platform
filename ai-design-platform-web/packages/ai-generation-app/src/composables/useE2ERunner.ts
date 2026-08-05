// ai-design-platform-web/packages/ai-generation-app/src/composables/useE2ERunner.ts
// E2E 执行引擎（task group 6.3/6.7）：
// - 结构化 DSL 用例（6.1）：target = {by: testid|text|role|css, value}
// - 等待条件（6.3）：waitForElement —— MutationObserver + 轮询，替代固定 sleep
// - 证据（6.3）：失败时收集 DOM 快照 + 用例执行期间 iframe postMessage 通道的
//   console/网络错误（复用 RUNTIME_CAPTURE_SCRIPT 的 'runtime-error' 消息）；
//   视觉截图待二期 —— html2canvas 不在应用依赖内，screenshot 保留 HTML 快照
// - requires_browser（6.7）：跳过并标注 status = 'skipped_requires_browser'
import { ref, type Ref } from 'vue'

export interface E2ETarget {
  by: 'testid' | 'text' | 'role' | 'css'
  value: string
}

export interface E2ETestStep {
  action: 'click' | 'input' | 'assert' | 'wait'
  target: E2ETarget
  value?: string
  assertion?: 'contains' | 'equals' | 'exists'
  timeout?: number
  description?: string
}

export interface E2ETestCase {
  id: string
  requirement_id: string
  scenario: string
  steps: E2ETestStep[]
  requires_browser?: boolean
  // 旧格式兼容（legacy cases）
  name?: string
  description?: string
}

export interface E2EEvidence {
  dom_snapshot?: string
  console_errors: string[]
  network_errors: string[]
  screenshot_note?: string
}

export type E2ECaseStatus = 'passed' | 'failed' | 'skipped_requires_browser'

export interface E2ECaseResult {
  caseId: string
  passed: boolean
  error?: string
  status?: E2ECaseStatus
  screenshot?: string
  evidence?: E2EEvidence
}

export const SKIPPED_REQUIRES_BROWSER: E2ECaseStatus = 'skipped_requires_browser'

const DEFAULT_TIMEOUT_MS = 5000
const POLL_INTERVAL_MS = 100
const DOM_SNAPSHOT_LIMIT = 20000

const VALID_ACTIONS = ['click', 'input', 'assert', 'wait']
const VALID_BY = ['testid', 'text', 'role', 'css']
const VALID_ASSERTIONS = ['contains', 'equals', 'exists']

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

/** 执行引擎 DSL 校验（spec: 非法 DSL 拒绝执行）—— 用例先于执行被拒绝，
 * 不进入任何步骤；后端 Designer 已做 schema 校验/重生成，此处为兜底 */
export function validateDslCase(testCase: E2ETestCase): string[] {
  const errors: string[] = []
  if (!testCase.id || !testCase.requirement_id || !testCase.scenario) {
    errors.push('id/requirement_id/scenario 缺失')
  }
  if (!Array.isArray(testCase.steps) || testCase.steps.length === 0) {
    errors.push('steps 为空')
    return errors
  }
  testCase.steps.forEach((step, i) => {
    if (!VALID_ACTIONS.includes(step.action)) {
      errors.push(`steps[${i + 1}] action 非法: ${step.action}`)
    }
    const target = step.target
    if (!target || !VALID_BY.includes(target.by) || !target.value) {
      errors.push(`steps[${i + 1}] target 非法: 需 {by ∈ ${VALID_BY.join('|')}, value 非空}`)
    }
    if (step.action === 'assert' && step.assertion && !VALID_ASSERTIONS.includes(step.assertion)) {
      errors.push(`steps[${i + 1}] assertion 非法: ${step.assertion}`)
    }
  })
  return errors
}

/** 按 DSL target 解析元素：testid / role / css 走 querySelector；text 精确匹配 */
export function resolveElement(doc: Document, target: E2ETarget): HTMLElement | null {
  const value = target.value
  switch (target.by) {
    case 'testid':
      return doc.querySelector(`[data-testid="${value}"]`) as HTMLElement | null
    case 'role':
      return doc.querySelector(`[role="${value}"]`) as HTMLElement | null
    case 'css':
      try {
        return doc.querySelector(value) as HTMLElement | null
      } catch {
        return null
      }
    case 'text': {
      // 精确匹配可见文本（点击/输入等定位用）
      const all = doc.querySelectorAll('body *')
      for (let i = 0; i < all.length; i++) {
        const el = all[i] as HTMLElement
        if (el.children.length === 0 && (el.textContent || '').trim() === value) return el
      }
      return null
    }
    default:
      return null
  }
}

/** 页面文本断言：任一元素的 textContent 包含 value */
export function documentContainsText(doc: Document, value: string): boolean {
  const all = doc.querySelectorAll('body *')
  for (let i = 0; i < all.length; i++) {
    if (((all[i] as HTMLElement).textContent || '').includes(value)) return true
  }
  return doc.body?.textContent?.includes(value) || false
}

/** 精确文本断言：存在 textContent 与 value 完全一致的叶子元素 */
export function documentHasExactText(doc: Document, value: string): boolean {
  const all = doc.querySelectorAll('body *')
  for (let i = 0; i < all.length; i++) {
    const el = all[i] as HTMLElement
    if (el.children.length === 0 && (el.textContent || '').trim() === value) return true
  }
  return false
}

/**
 * 等待条件（6.3）：MutationObserver + 轮询，直到元素出现或超时。
 * 返回解析后的元素；超时返回 null（调用方按步骤语义决定是否失败）。
 */
export function waitForElement(
  doc: Document,
  target: E2ETarget,
  timeoutMs: number = DEFAULT_TIMEOUT_MS,
): Promise<HTMLElement | null> {
  return new Promise((resolve) => {
    const start = Date.now()
    let timer: number | null = null
    let observer: MutationObserver | null = null

    const cleanup = () => {
      if (timer !== null) {
        clearTimeout(timer)
        timer = null
      }
      if (observer) {
        observer.disconnect()
        observer = null
      }
    }

    const schedule = () => {
      if (timer !== null) return
      timer = window.setTimeout(() => {
        timer = null
        check()
      }, POLL_INTERVAL_MS)
    }

    const check = () => {
      const el = resolveElement(doc, target)
      if (el) {
        cleanup()
        resolve(el)
        return
      }
      if (Date.now() - start >= timeoutMs) {
        cleanup()
        resolve(null)
        return
      }
      schedule()
    }

    check()
    if (typeof MutationObserver !== 'undefined' && doc.documentElement) {
      observer = new MutationObserver(() => {
        if (timer === null) schedule()
      })
      observer.observe(doc.documentElement, {
        childList: true,
        subtree: true,
        attributes: true,
      })
    }
  })
}

async function captureHtmlScreenshot(iframe: HTMLIFrameElement): Promise<string> {
  try {
    const doc = iframe.contentDocument
    if (!doc) return ''
    const html = doc.documentElement.outerHTML
    return `data:text/html;base64,${btoa(unescape(encodeURIComponent(html)))}`
  } catch {
    return ''
  }
}

function captureDomSnapshot(doc: Document): string {
  try {
    const html = doc.body ? doc.body.outerHTML : doc.documentElement.outerHTML
    return html.slice(0, DOM_SNAPSHOT_LIMIT)
  } catch {
    return ''
  }
}

/**
 * 用例执行期间的证据收集：订阅 iframe 的 postMessage 通道
 * （RUNTIME_CAPTURE_SCRIPT 的 'runtime-error' 消息），把 console/网络错误
 * 分别收进 evidence；stop() 在用例结束时移除监听。
 * M8 (review): 只接受来自预览 iframe（ev.source === iframe.contentWindow）
 * 的消息 —— 捕获脚本在 iframe 内 postMessage 到 window.parent，来源校验
 * 防止其它窗口的噪音污染用例证据。
 */
export function startEvidenceCollector(iframe: HTMLIFrameElement): {
  evidence: E2EEvidence
  stop: () => void
} {
  const evidence: E2EEvidence = { console_errors: [], network_errors: [] }
  const onMessage = (ev: MessageEvent) => {
    const data = ev.data
    if (!data || typeof data !== 'object') return
    if (ev.source && iframe.contentWindow && ev.source !== iframe.contentWindow) return
    if (data.type === 'runtime-error' && Array.isArray(data.errors)) {
      for (const err of data.errors) {
        if (!err) continue
        const message = String(err.message || '').slice(0, 500)
        if (err.type === 'network') {
          const url = err.url ? ` (${err.url})` : ''
          if (message || url) evidence.network_errors.push(`${message}${url}`)
        } else if (message) {
          evidence.console_errors.push(`${err.type || 'console_error'}: ${message}`)
        }
      }
    } else if (data.type === 'err' && data.message) {
      // 旧版捕获脚本通道
      evidence.console_errors.push(`legacy: ${String(data.message).slice(0, 500)}`)
    }
  }
  window.addEventListener('message', onMessage)
  return {
    evidence,
    stop: () => window.removeEventListener('message', onMessage),
  }
}

async function executeStep(doc: Document, step: E2ETestStep): Promise<void> {
  const target = step.target
  const timeoutMs = step.timeout || DEFAULT_TIMEOUT_MS

  switch (step.action) {
    case 'click': {
      const el = await waitForElement(doc, target, timeoutMs)
      if (!el) throw new Error(`Element not found: ${target.by}=${target.value}`)
      el.click()
      await sleep(50)
      break
    }
    case 'input': {
      const el = await waitForElement(doc, target, timeoutMs)
      if (!el) throw new Error(`Element not found: ${target.by}=${target.value}`)
      const input = el as HTMLInputElement
      const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
        window.HTMLInputElement.prototype, 'value',
      )?.set
      nativeInputValueSetter?.call(input, step.value || '')
      input.dispatchEvent(new Event('input', { bubbles: true }))
      await sleep(50)
      break
    }
    case 'assert': {
      const assertion = step.assertion || 'exists'
      if (target.by === 'text') {
        // 文本断言直接面向页面内容（DSL 示例：assert text "第 2 页" contains）
        if (assertion === 'equals') {
          if (!documentHasExactText(doc, target.value)) {
            throw new Error(`Assertion failed: expected text "${target.value}" (equals) not found`)
          }
        } else {
          if (!documentContainsText(doc, target.value)) {
            throw new Error(`Assertion failed: expected text "${target.value}" not found in page`)
          }
        }
        break
      }
      const el = await waitForElement(doc, target, timeoutMs)
      if (!el) throw new Error(`Assertion failed: element not found: ${target.by}=${target.value}`)
      const text = el.textContent || ''
      const expected = step.value || ''
      if (assertion === 'contains' && expected && !text.includes(expected)) {
        throw new Error(
          `Assertion failed: expected "${expected}" in ${target.by}=${target.value}, got "${text.slice(0, 100)}"`,
        )
      }
      if (assertion === 'equals' && expected && text.trim() !== expected.trim()) {
        throw new Error(
          `Assertion failed: expected exactly "${expected}" in ${target.by}=${target.value}, got "${text.slice(0, 100)}"`,
        )
      }
      break
    }
    case 'wait': {
      // wait：目标元素出现（轮询至超时）或按毫秒固定等待
      if (target && target.value) {
        const el = await waitForElement(doc, target, timeoutMs)
        if (!el) {
          throw new Error(`Element not found (wait timeout ${timeoutMs}ms): ${target.by}=${target.value}`)
        }
      } else {
        const ms = parseInt(step.value || '1000', 10) || 1000
        await sleep(ms)
      }
      break
    }
    default:
      throw new Error(`Unknown action: ${(step as E2ETestStep).action}`)
  }
}

export function useE2ERunner(previewFrameRef: Ref<HTMLIFrameElement | null>) {
  const results = ref<E2ECaseResult[]>([])
  const currentCaseIndex = ref(-1)
  const isRunning = ref(false)

  async function executeCase(testCase: E2ETestCase): Promise<E2ECaseResult> {
    // 6.7：requires_browser 复杂用例 —— 一期跳过，列入人工执行清单，不静默失败
    if (testCase.requires_browser) {
      return {
        caseId: testCase.id,
        passed: false,
        status: SKIPPED_REQUIRES_BROWSER,
        error: 'requires_browser：待人工/后端浏览器执行',
        evidence: { console_errors: [], network_errors: [] },
      }
    }

    // 非法 DSL 拒绝执行（spec 场景）：校验不过直接拒绝，不进入步骤执行
    const dslErrors = validateDslCase(testCase)
    if (dslErrors.length > 0) {
      return {
        caseId: testCase.id,
        passed: false,
        status: 'failed',
        error: `非法 DSL 用例，拒绝执行：${dslErrors.join('；')}`,
        evidence: { console_errors: [], network_errors: [] },
      }
    }

    const iframe = previewFrameRef.value
    if (!iframe?.contentDocument) {
      return {
        caseId: testCase.id,
        passed: false,
        status: 'failed',
        error: 'Preview iframe not available',
        evidence: { console_errors: [], network_errors: [] },
      }
    }

    const collector = startEvidenceCollector(iframe)
    const doc = iframe.contentDocument
    try {
      for (const step of testCase.steps) {
        await executeStep(doc, step)
      }
      collector.stop()
      return {
        caseId: testCase.id,
        passed: true,
        status: 'passed',
        evidence: collector.evidence,
      }
    } catch (e: any) {
      collector.stop()
      const snapshot = captureDomSnapshot(doc)
      const screenshot = await captureHtmlScreenshot(iframe)
      return {
        caseId: testCase.id,
        passed: false,
        status: 'failed',
        error: e.message || 'Unknown error',
        screenshot,
        evidence: {
          dom_snapshot: snapshot,
          console_errors: collector.evidence.console_errors,
          network_errors: collector.evidence.network_errors,
          // 视觉截图待二期：html2canvas 不在应用依赖内（已核对 package.json）；
          // 一期证据集 = DOM 快照 + console/网络日志。
          screenshot_note:
            '视觉渲染截图待二期（html2canvas 不在依赖内）：本期提供 DOM 快照 + console/网络证据',
        },
      }
    }
  }

  async function executeAll(
    testCases: E2ETestCase[],
    onCaseComplete: (result: E2ECaseResult) => void,
  ): Promise<E2ECaseResult[]> {
    isRunning.value = true
    results.value = []

    for (let i = 0; i < testCases.length; i++) {
      currentCaseIndex.value = i
      const result = await executeCase(testCases[i])
      results.value.push(result)
      onCaseComplete(result)
    }

    isRunning.value = false
    currentCaseIndex.value = -1
    return results.value
  }

  function reset() {
    results.value = []
    currentCaseIndex.value = -1
    isRunning.value = false
  }

  return {
    results,
    currentCaseIndex,
    isRunning,
    executeCase,
    executeAll,
    reset,
  }
}

export function isSkippedResult(result: E2ECaseResult): boolean {
  return result.status === SKIPPED_REQUIRES_BROWSER
}
