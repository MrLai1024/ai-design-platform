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
  stage?: Stage
  reasoningContent?: string
  reasoningDurationMs?: number
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

/** 工作流阶段 */
export type Stage = 'idle' | 'analysis' | 'design' | 'code'

/** 阶段状态 */
export type StageStatus = 'pending' | 'active' | 'done'

/** 各阶段产出 */
export interface StageOutputs {
  analysis: string | null
  design: string | null
}

/** 代码实现阶段 Tab */
export type CodeViewTab = 'preview' | 'files'

/** 右侧面板视图 */
export type RightPanelView = 'stage-output' | 'preview' | 'files'

/** 步骤条节点定义 */
export interface StepNode {
  key: Stage
  label: string
  status: StageStatus
}
