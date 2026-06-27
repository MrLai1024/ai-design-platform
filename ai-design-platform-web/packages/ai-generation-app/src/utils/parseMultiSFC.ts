// src/utils/parseMultiSFC.ts
import type { ParsedCodeBlock } from '@/types/generation'

/**
 * 从流式累积的 AI 回复中提取多文件 SFC。
 * 格式: ## FileName.vue\n```vue\n...code...\n```
 */
export function parseMultiSFC(text: string): ParsedCodeBlock[] {
  const headingRe = /^#{2,3}\s+(.+?\.vue)\b/gm
  const fenceRe = /```vue\s*\n([\s\S]*?)```/g

  const headings: Array<{ filename: string; matchEnd: number; matchStart: number }> = []
  let m: RegExpExecArray | null
  while ((m = headingRe.exec(text)) !== null) {
    headings.push({ filename: m[1] || '', matchStart: m.index, matchEnd: m.index + m[0].length })
  }

  if (headings.length === 0) return []

  const files: ParsedCodeBlock[] = []
  for (let i = 0; i < headings.length; i++) {
    const { filename, matchEnd } = headings[i]!
    const end = i + 1 < headings.length ? headings[i + 1]!.matchStart : text.length
    const section = text.slice(matchEnd, end)

    fenceRe.lastIndex = 0
    const fenceMatch = fenceRe.exec(section)
    if (fenceMatch) {
      files.push({
        filename,
        language: 'vue',
        code: (fenceMatch[1] || '').trim(),
        startLine: matchEnd,
      })
    }
  }

  return files
}

/**
 * 当无多文件标记时，提取第一个 ```vue 代码块作为 App.vue
 */
export function parseSingleCodeBlock(text: string): ParsedCodeBlock | null {
  const fenceRe = /```(?:vue|html)\s*\n([\s\S]*?)```/
  const match = fenceRe.exec(text)
  if (!match) return null

  return {
    filename: 'App.vue',
    language: 'vue',
    code: (match[1] || '').trim(),
    startLine: match.index,
  }
}
