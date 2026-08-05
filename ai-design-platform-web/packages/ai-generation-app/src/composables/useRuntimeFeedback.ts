// src/composables/useRuntimeFeedback.ts
// 5.4 L3 运行时证据：预览 iframe 的 console/未捕获异常/网络失败错误 → 批量
// POST /api/v1/generation/runtime-feedback → 后端 Verifier L3 消费。
// 替换语义：每次 flush 发送当前构建的快照；新构建加载时 clear() 清空本地
// 缓冲并上报空批次（后端清空该 generation 的运行时错误）。
//
// Review fix (Important — 构建竞态): 后端是"整批替换"语义，若旧构建的
// flush POST 在 clear() 之后才落地，会覆盖新构建的清空 → 假 L3 失败。
// 方案：build-epoch。每次 POST 发送时捕获 epoch；clear() 递增 epoch；
// 在途 POST 成功返回后发现 epoch 已变（本批次属于旧构建）→ 立即补发一个
// 空批次，把后端恢复到清空状态。

import { ref } from 'vue'
import { useGenerationStore } from '@/stores/generation'

export interface RuntimeFeedbackError {
  type: 'console_error' | 'uncaught' | 'unhandledrejection' | 'network' | string
  message: string
  stack?: string
  url?: string
}

const FLUSH_MS = 2000

export function useRuntimeFeedback() {
  const store = useGenerationStore()
  const buffer = ref<RuntimeFeedbackError[]>([])
  let flushTimer: number | null = null
  // 构建代际：clear()（新构建加载）递增；在途 POST 落地后比对，
  // 代际不符 → 本批次属于旧构建 → 补发空批次。
  let epoch = 0

  function normalize(e: RuntimeFeedbackError): RuntimeFeedbackError {
    return {
      type: e.type || 'console_error',
      message: String(e.message || '').slice(0, 500),
      stack: e.stack ? String(e.stack).slice(0, 1000) : undefined,
      url: e.url ? String(e.url).slice(0, 500) : undefined,
    }
  }

  /** iframe 捕获到的错误 → 缓冲 + 定时批量上报 */
  function capture(errors: RuntimeFeedbackError[]): void {
    for (const e of errors || []) buffer.value.push(normalize(e))
    scheduleFlush()
  }

  /** 新构建加载：丢弃旧缓冲（错误属于旧构建）并上报空批次清空后端 */
  function clear(): void {
    epoch += 1
    buffer.value = []
    if (flushTimer) {
      clearTimeout(flushTimer)
      flushTimer = null
    }
    void postBatch([])
  }

  function scheduleFlush(): void {
    if (flushTimer) return
    flushTimer = window.setTimeout(() => {
      flushTimer = null
      void flush()
    }, FLUSH_MS)
  }

  /** 立即把缓冲的当前批次 POST 到后端（空批次 = 清空） */
  async function flush(): Promise<boolean> {
    if (buffer.value.length === 0) return false
    const batch = buffer.value.splice(0, buffer.value.length)
    return postBatch(batch)
  }

  async function postBatch(batch: RuntimeFeedbackError[]): Promise<boolean> {
    if (!store.currentGenerationId) return false
    const sentEpoch = epoch
    try {
      const resp = await fetch('/api/v1/generation/runtime-feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          generation_id: store.currentGenerationId,
          errors: batch,
        }),
      })
      if (!resp.ok) return false
      if (sentEpoch !== epoch) {
        // 本批次属于旧构建（clear 已发生）→ 补发空批次，
        // 防止 stale 错误覆盖新构建的清空状态。
        void postBatch([])
      }
      return true
    } catch {
      /* 上报失败不影响预览 */
      return false
    }
  }

  return { buffer, capture, clear, flush }
}
