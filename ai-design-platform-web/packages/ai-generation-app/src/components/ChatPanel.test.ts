// src/components/ChatPanel.test.ts — 10.1 范围确认卡「确认」→ 强制 resume 同一 runner
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ChatPanel from './ChatPanel.vue'
import { useGenerationStore } from '@/stores/generation'

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
  } as unknown as Response
}

describe('ChatPanel — 反馈范围确认卡 wiring (10.1 review fix)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.restoreAllMocks()
  })

  it('scope_confirm 确认 → forceResumeNextConfirm: 下次 confirmStage resume 同一 runner', async () => {
    const store = useGenerationStore()
    store.setStage('code')
    store.setGenerationId('gen-scope-x')
    store.addManagerCard({
      card: 'confirm_card',
      title: '确认 · 功能实现',
      content: '用户反馈提出新增需求范围，Manager 需你确认后才执行',
      options: ['确认', '重新生成'],
      data: { node: 'code', scope_confirm: true },
      stage: 'code',
    })
    const fetchMock = vi.fn().mockResolvedValue(sseResponse([]))
    vi.stubGlobal('fetch', fetchMock)

    const wrapper = mount(ChatPanel)
    const buttons = wrapper.findAll('button')
    const confirmBtn = buttons.find((b) => b.text() === '确认')
    expect(confirmBtn).toBeTruthy()
    await confirmBtn!.trigger('click')
    await new Promise((r) => setTimeout(r, 0))

    const call = fetchMock.mock.calls[0]!
    expect(call[0]).toBe('/api/v1/generation/stream')
    const body = JSON.parse((call[1] as RequestInit).body as string)
    // 处置挂起在当前 runner — 必须 resume 同一 runner (fresh-start 新 UUID 会丢失)
    expect(body.mode).toBe('resume')
    expect(body.generation_id).toBe('gen-scope-x')
  })
})
