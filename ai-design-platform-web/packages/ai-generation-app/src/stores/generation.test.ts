// src/stores/generation.test.ts
import { describe, it, expect, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useGenerationStore } from './generation'

describe('generation store — manager cards & manual mode', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('addManagerCard pushes an assistant message with meta', () => {
    const store = useGenerationStore()
    const id = store.addManagerCard({
      card: 'summary_card',
      title: '需求分析阶段产出总结',
      content: 'PRD 总结…',
      stage: 'analysis',
    })

    expect(id).toBeTruthy()
    expect(store.messages).toHaveLength(1)
    const msg = store.messages[0]!
    expect(msg.role).toBe('assistant')
    expect(msg.isStreaming).toBe(false)
    expect(msg.stage).toBe('analysis')
    expect(msg.meta).toEqual({
      card: 'summary_card',
      title: '需求分析阶段产出总结',
      content: 'PRD 总结…',
    })
  })

  it('addManagerCard keeps options and data in meta', () => {
    const store = useGenerationStore()
    store.addManagerCard({
      card: 'diagnosis_card',
      title: '需要你的决策',
      content: '自动流程遇到问题',
      options: ['继续自主', '转人工'],
      data: { reason: 'loop limit reached' },
    })

    const meta = store.messages[0]!.meta!
    expect(meta.card).toBe('diagnosis_card')
    expect(meta.options).toEqual(['继续自主', '转人工'])
    expect(meta.data).toEqual({ reason: 'loop limit reached' })
  })

  it('setManualMode toggles manualMode and resetAll clears it', () => {
    const store = useGenerationStore()
    expect(store.manualMode).toBe(false)
    store.setManualMode(true)
    expect(store.manualMode).toBe(true)
    store.resetAll()
    expect(store.manualMode).toBe(false)
    expect(store.messages).toHaveLength(0)
  })

  it('9.3 (C1): lastVerdicts records gate verdicts; clearFailedStageOutput drops the failed copy', () => {
    const store = useGenerationStore()
    store.setStageOutput('design', '方案文本')
    store.setLastVerdict('design', 'redo')
    expect(store.lastVerdicts['design']).toBe('redo')
    // redo 裁决 → 前端镜像清空失败产物 (避免被下次 prefill 携带)
    store.clearFailedStageOutput('design')
    expect(store.stageOutputs.design).toBeNull()
    // pass 裁决不要求清空
    store.setLastVerdict('analysis', 'pass')
    expect(store.lastVerdicts['analysis']).toBe('pass')
    store.resetAll()
    expect(store.lastVerdicts).toEqual({})
  })
})
