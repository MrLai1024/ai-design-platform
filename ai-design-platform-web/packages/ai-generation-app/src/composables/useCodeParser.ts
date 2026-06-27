// src/composables/useCodeParser.ts
import { watch } from 'vue'
import { useGenerationStore } from '@/stores/generation'
import { parseMultiSFC, parseSingleCodeBlock } from '@/utils/parseMultiSFC'
import type { FileEntry, ParsedCodeBlock } from '@/types/generation'

export function useCodeParser() {
  const store = useGenerationStore()

  // 监听最后一条 AI 消息的 content 变化，实时解析代码块
  watch(
    () => store.lastAssistantMessage?.content,
    (content) => {
      if (!content) return
      const blocks = detectCodeBlocks(content)
      if (blocks.length > 0) {
        updateFiles(blocks)
      }
    },
  )

  function detectCodeBlocks(text: string): ParsedCodeBlock[] {
    // 先尝试多文件解析
    const multi = parseMultiSFC(text)
    if (multi.length > 0) return multi

    // 无多文件标记 → 单文件模式
    const single = parseSingleCodeBlock(text)
    if (single) return [single]

    return []
  }

  function updateFiles(blocks: ParsedCodeBlock[]): void {
    for (const block of blocks) {
      const existing = store.files.get(block.filename)

      // 消重：内容相同则跳过
      if (existing && existing.content === block.code) continue

      const entry: FileEntry = {
        filename: block.filename,
        content: block.code,
        language: 'vue',
        isDirty: true,
        source: 'ai',
      }
      store.setFile(block.filename, entry)
    }

    // 自动切换到第一个文件
    if (blocks.length > 0 && blocks[0]) {
      store.setActiveFile(blocks[0].filename)
    }
  }

  // 同时更新消息中的 codeBlocks 元数据
  watch(
    () => store.lastAssistantMessage?.content,
    (content) => {
      if (!content || !store.lastAssistantMessage) return
      const blocks = detectCodeBlocks(content)
      if (blocks.length > 0) {
        store.lastAssistantMessage.codeBlocks = blocks
      }
    },
  )

  return { detectCodeBlocks }
}
