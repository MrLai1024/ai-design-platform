// src/components/E2EStagePanel.test.ts
// I1 (review): PreviewFrame defineExpose({ iframe }) → E2EStagePanel 组件 ref
// watcher → emit 'preview-iframe' → GenerationView 写入 useE2ERunner 的
// previewFrameRef（模板中不能直接传 Ref prop —— 会被自动解包）。
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import E2EStagePanel from './E2EStagePanel.vue'
import { useGenerationStore } from '@/stores/generation'

// 桩 PreviewFrame 模块（真实模块在 vitest 环境会拉 esbuild-wasm 失败）：
// 模拟 defineExpose({ iframe }) 的真实 iframe
vi.mock('./PreviewFrame.vue', () => ({
  default: {
    name: 'PreviewFrame',
    setup(_props: any, { expose }: any) {
      const iframe = document.createElement('iframe')
      expose({ iframe })
      return () => null
    },
  },
}))

function mountPanel(onPreviewIframe: (iframe: HTMLIFrameElement | null) => void) {
  return mount(E2EStagePanel, {
    props: { onPreviewIframe },
    global: {
      stubs: {
        StreamDocument: true,
        TestCaseProgress: true,
      },
    },
  })
}

describe('E2EStagePanel — preview iframe propagation (I1)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('emits the exposed preview iframe in phase 2', async () => {
    const store = useGenerationStore()
    store.setE2ETestCases([
      { id: 'tc-r01-1', requirement_id: 'R-01', scenario: '分页切换', steps: [] },
    ])
    store.confirmE2ECases() // 确认 → phase 2 渲染 PreviewFrame

    const emitted: Array<HTMLIFrameElement | null> = []
    mountPanel((iframe) => emitted.push(iframe))
    await flushPromises()

    // useE2ERunner 的 previewFrameRef 被 PreviewFrame 的真实 iframe 填充
    expect(emitted.length).toBeGreaterThan(0)
    const iframe = emitted[emitted.length - 1]
    expect(iframe).not.toBeNull()
    expect(iframe!.tagName).toBe('IFRAME')
  })

  it('does not emit in phase 1 (runner not active)', async () => {
    const store = useGenerationStore()
    store.setE2ETestCases([
      { id: 'tc-r01-1', requirement_id: 'R-01', scenario: '分页切换', steps: [] },
    ])
    // 未确认 → phase 1（只展示用例清单，无 PreviewFrame）

    const emitted: Array<HTMLIFrameElement | null> = []
    mountPanel((iframe) => emitted.push(iframe))
    await flushPromises()

    expect(emitted).toHaveLength(0)
  })
})
