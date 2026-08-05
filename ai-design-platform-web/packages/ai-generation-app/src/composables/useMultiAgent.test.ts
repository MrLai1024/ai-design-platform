// src/composables/useMultiAgent.test.ts — brainstorm wiring (task group 3)
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useMultiAgent } from './useMultiAgent'
import { useGenerationStore } from '../stores/generation'

function mockFetchResponse(payload: unknown) {
  return vi.fn().mockResolvedValue({
    ok: true,
    json: async () => payload,
  })
}

describe('useMultiAgent — brainstorm agenda wiring (task group 3)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.restoreAllMocks()
  })

  it('startBrainstorm POSTs the requirement and stores session id + manager card', async () => {
    const store = useGenerationStore()
    const fetchMock = mockFetchResponse({
      generation_id: 'bs-session-1',
      converged: false,
      coverage: 0.5,
      events: [
        {
          _t: 'manager_message',
          stage: 'analysis',
          card: 'summary_card',
          title: '需求画像 · 头脑风暴',
          content: '需求类型：admin_system',
          options: [],
          data: { node: 'analysis' },
        },
      ],
    })
    vi.stubGlobal('fetch', fetchMock)

    const { startBrainstorm } = useMultiAgent()
    await startBrainstorm('做一个后台管理系统')

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/generation/brainstorm',
      expect.objectContaining({
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: expect.stringContaining('"text":"做一个后台管理系统"'),
      }),
    )
    // 会话 id 入库，后续轮次复用
    expect(store.currentGenerationId).toBe('bs-session-1')
    expect(store.brainstormConverged).toBe(false)
    // 用户消息 + manager_message 卡片消息
    expect(store.messages[0]!.role).toBe('user')
    expect(store.messages.at(-1)!.meta?.card).toBe('summary_card')
  })

  it('sendBrainstormTurn threads session id + item_id and applies converged flag', async () => {
    const store = useGenerationStore()
    store.setGenerationId('bs-session-1')
    const fetchMock = mockFetchResponse({
      generation_id: 'bs-session-1',
      converged: true,
      coverage: 1.0,
      events: [
        {
          _t: 'manager_message',
          stage: 'analysis',
          card: 'confirm_card',
          title: '确认 · 需求分析',
          content: '需求澄清已收敛',
          options: ['确认开始', '还有疑问'],
          data: { node: 'analysis' },
        },
      ],
    })
    vi.stubGlobal('fetch', fetchMock)

    const { sendBrainstormTurn } = useMultiAgent()
    await sendBrainstormTurn('确认，可以开始')

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/generation/brainstorm',
      expect.objectContaining({
        body: expect.stringContaining('"generation_id":"bs-session-1"'),
      }),
    )
    expect(store.brainstormConverged).toBe(true)
    const card = store.messages.at(-1)!.meta!
    expect(card.card).toBe('confirm_card')
    expect(card.options).toEqual(['确认开始', '还有疑问'])
  })

  it('sendBrainstormTurn with item_id passes it through for question cards', async () => {
    const store = useGenerationStore()
    store.setGenerationId('bs-session-1')
    const fetchMock = mockFetchResponse({
      generation_id: 'bs-session-1',
      converged: false,
      coverage: 0.67,
      events: [],
    })
    vi.stubGlobal('fetch', fetchMock)

    const { sendBrainstormTurn } = useMultiAgent()
    await sendBrainstormTurn('RBAC', 'a1')

    const body = JSON.parse((fetchMock.mock.calls[0]![1] as RequestInit).body as string)
    expect(body.generation_id).toBe('bs-session-1')
    expect(body.item_id).toBe('a1')
  })
})

describe('useMultiAgent — 9.3 continuity fixes (C1/I5 review)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.restoreAllMocks()
  })

  /** 一次性 SSE 响应: 事件帧 + 立即结束的 reader */
  function sseResponse(frames: Array<Record<string, unknown>>) {
    const payload = frames.map((f) => `data: ${JSON.stringify(f)}\n\n`).join('')
    const bytes = new TextEncoder().encode(payload)
    let sent = false
    return {
      ok: true,
      body: {
        getReader: () => ({
          read: async () => {
            if (sent) return { done: true, value: undefined }
            sent = true
            return { done: false, value: bytes }
          },
        }),
      },
    }
  }

  it('C1: manager_verdict redo clears the failed stage output copy', async () => {
    const store = useGenerationStore()
    store.setStageOutput('design', '失败的方案')
    const fetchMock = vi.fn().mockResolvedValue(sseResponse([
      { _t: 'meta', generation_id: 'gen-x' },
      { _t: 'manager_verdict', stage: 'design', decision: 'redo', reason: 'L2 缺失' },
    ]))
    vi.stubGlobal('fetch', fetchMock)

    const { startGraphGeneration } = useMultiAgent()
    await startGraphGeneration('做一个页面')

    expect(store.lastVerdicts['design']).toBe('redo')
    expect(store.stageOutputs.design).toBeNull()
  })

  it('C1: manager_verdict pass keeps the stage output copy', async () => {
    const store = useGenerationStore()
    store.setStageOutput('analysis', 'PRD 全文')
    const fetchMock = vi.fn().mockResolvedValue(sseResponse([
      { _t: 'meta', generation_id: 'gen-x' },
      { _t: 'manager_verdict', stage: 'analysis', decision: 'pass', reason: '' },
    ]))
    vi.stubGlobal('fetch', fetchMock)

    const { startGraphGeneration } = useMultiAgent()
    await startGraphGeneration('做一个页面')

    expect(store.lastVerdicts['analysis']).toBe('pass')
    expect(store.stageOutputs.analysis).toBe('PRD 全文')
  })

  it('C1: confirmStage resumes the same runner for a gate-failed stage', async () => {
    const store = useGenerationStore()
    store.setStage('design')
    store.setGenerationId('gen-x')
    store.setLastVerdict('design', 'redo')
    store.setStageOutput('design', '失败的方案')
    const fetchMock = vi.fn().mockResolvedValue(sseResponse([]))
    vi.stubGlobal('fetch', fetchMock)

    const { confirmStage } = useMultiAgent()
    await confirmStage('design')

    const body = JSON.parse((fetchMock.mock.calls[0]![1] as RequestInit).body as string)
    expect(body.mode).toBe('resume')
    expect(body.generation_id).toBe('gen-x')
    expect(body.messages).toEqual([])
    expect(body.skip_analysis).toBeUndefined()
  })

  it('C1: confirmStage keeps the fresh-start prefill when the stage verdict passed', async () => {
    const store = useGenerationStore()
    store.setStage('design')
    store.setGenerationId('gen-x')
    store.setStageOutput('analysis', 'PRD 全文')
    store.setStageOutput('design', '方案全文')
    const fetchMock = vi.fn().mockResolvedValue(sseResponse([]))
    vi.stubGlobal('fetch', fetchMock)

    const { confirmStage } = useMultiAgent()
    await confirmStage('design')

    const body = JSON.parse((fetchMock.mock.calls[0]![1] as RequestInit).body as string)
    expect(body.mode).toBe('graph')
    expect(body.skip_analysis).toBe(true)
    expect(body.messages).toHaveLength(2)
  })
})
