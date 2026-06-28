// src/types/generation.ts

/** 组件库标识 */
export type ComponentLibrary = 'tailwind' | 'antd' | 'element' | 'echarts'

/** 消息中的代码块 */
export interface ParsedCodeBlock {
  filename: string
  language: string
  code: string
  startLine: number
}

/** 对话消息 */
export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  codeBlocks: ParsedCodeBlock[]
  timestamp: number
  isStreaming: boolean
}

/** 生成的文件条目 */
export interface FileEntry {
  filename: string
  content: string
  language: 'vue' | 'typescript' | 'javascript' | 'css'
  isDirty: boolean
  source: 'ai' | 'user'
}

/** 组件库配置 */
export interface LibraryConfig {
  key: ComponentLibrary
  label: string
  cdnUrls: string[]
  docInjection: string
}

/** 编译结果 */
export interface CompileResult {
  code: string | null
  css: string
  scopeId: string | null
  hasTemplate: boolean
  hasScript: boolean
}

/** 编译选项 */
export interface CompileOptions {
  filename?: string
}
