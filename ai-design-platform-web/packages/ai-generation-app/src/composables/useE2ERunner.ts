// ai-design-platform-web/packages/ai-generation-app/src/composables/useE2ERunner.ts
import { ref, type Ref } from 'vue'

export interface E2ETestStep {
  action: 'click' | 'input' | 'assert' | 'wait'
  target: string
  value?: string
  description: string
}

export interface E2ETestCase {
  id: string
  name: string
  description: string
  steps: E2ETestStep[]
}

export interface E2ECaseResult {
  caseId: string
  passed: boolean
  error?: string
  screenshot?: string
}

async function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

async function captureScreenshot(iframe: HTMLIFrameElement): Promise<string> {
  try {
    const doc = iframe.contentDocument
    if (!doc) return ''
    const html = doc.documentElement.outerHTML
    return `data:text/html;base64,${btoa(unescape(encodeURIComponent(html)))}`
  } catch {
    return ''
  }
}

async function executeStep(doc: Document, step: E2ETestStep): Promise<void> {
  const el = doc.querySelector(step.target) as HTMLElement | null

  if (!el && step.action !== 'wait') {
    throw new Error(`Element not found: ${step.target}`)
  }

  switch (step.action) {
    case 'click': {
      el!.click()
      await sleep(100)
      break
    }
    case 'input': {
      const input = el as HTMLInputElement
      const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
        window.HTMLInputElement.prototype, 'value'
      )?.set
      nativeInputValueSetter?.call(input, step.value || '')
      input.dispatchEvent(new Event('input', { bubbles: true }))
      await sleep(100)
      break
    }
    case 'assert': {
      const text = el?.textContent || ''
      const expected = step.value || ''
      if (!text.includes(expected)) {
        throw new Error(
          `Assertion failed: expected "${expected}" in "${step.target}", got "${text.slice(0, 100)}"`
        )
      }
      break
    }
    case 'wait': {
      const ms = parseInt(step.value || '1000', 10) || 1000
      await sleep(ms)
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
    const iframe = previewFrameRef.value
    if (!iframe?.contentDocument) {
      return {
        caseId: testCase.id,
        passed: false,
        error: 'Preview iframe not available',
      }
    }

    const doc = iframe.contentDocument
    try {
      for (const step of testCase.steps) {
        await executeStep(doc, step)
      }
      return { caseId: testCase.id, passed: true }
    } catch (e: any) {
      const screenshot = await captureScreenshot(iframe)
      return {
        caseId: testCase.id,
        passed: false,
        error: e.message || 'Unknown error',
        screenshot,
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
