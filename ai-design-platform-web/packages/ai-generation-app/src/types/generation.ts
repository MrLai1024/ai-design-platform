// src/types/generation.ts


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
  interrupted?: boolean
  /** Manager 结构化消息卡片（meta 存在时消息以卡片渲染） */
  meta?: ManagerCardMeta
}

/** Manager 卡片类型（后端 manager_message 事件的 card 判别值） */
export type ManagerCardType =
  | 'summary_card'
  | 'verdict_card'
  | 'diagnosis_card'
  | 'confirm_card'
  | 'proposal_card'
  | 'coverage_matrix'
  | 'question_card'

/** Manager 卡片元数据 */
export interface ManagerCardMeta {
  card: ManagerCardType
  title?: string
  content?: string
  options?: string[]
  data?: Record<string, any>
}

/** 新增 Manager 卡片的载荷（可附带阶段） */
export interface ManagerCardPayload extends ManagerCardMeta {
  stage?: Stage
}

/** Manager 意图路由结果（后端 classify_intent 的 intent 值） */
export type ManagerIntent = 'reply_qa' | 'proceed' | 'feedback' | 'escalate' | 'ask_why'

/** 生成的文件条目 */
export interface FileEntry {
  filename: string
  content: string
  language: 'vue' | 'typescript' | 'javascript' | 'css'
  isDirty: boolean
  source: 'ai' | 'user'
}

/** 组件库标识（与 useComponentDocs LIBRARY_CONFIGS 的 key 对应） */
export type ComponentLibrary = 'tailwind' | 'antd' | 'element' | 'echarts'

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
export type Stage = 'idle' | 'analysis' | 'design' | 'code' | 'e2e' | 'done'

/** 阶段状态 */
export type StageStatus = 'pending' | 'active' | 'done'

/** 各阶段产出 */
export interface StageOutputs {
  analysis: string | null
  design: string | null
  code: string | null
  e2e: string | null
}

/** 代码实现阶段 Tab */
export type CodeViewTab = 'preview' | 'files' | 'trace'

/** 右侧面板视图 */
export type RightPanelView = 'stage-output' | 'preview' | 'files' | 'trace'

/** 步骤条节点定义 */
export interface StepNode {
  key: Stage
  label: string
  status: StageStatus
}

export type GraphEventType =
  | 'stage_start'
  | 'stage_complete'
  | 'stage_rollback'
  | 'e2e_start'
  | 'e2e_execute'
  | 'e2e_case_result'
  | 'e2e_complete'
  | 'human_confirm_required'
  | 'loop_warning'
  | 'loop_break'
  | 'token'
  | 'complete'
  | 'error'

// E2E types (shared with backend DSL, task group 6)
export interface E2ETarget {
  by: 'testid' | 'text' | 'role' | 'css'
  value: string
}

export interface E2ETestStep {
  action: 'click' | 'input' | 'assert' | 'wait'
  target: E2ETarget
  value?: string
  assertion?: 'contains' | 'equals' | 'exists'
  timeout?: number
  description?: string
}

export interface E2ETestCase {
  id: string
  requirement_id: string
  scenario: string
  steps: E2ETestStep[]
  requires_browser?: boolean
  // 旧格式兼容
  name?: string
  description?: string
}

export interface E2EEvidence {
  dom_snapshot?: string
  console_errors: string[]
  network_errors: string[]
  screenshot_note?: string
}

export interface E2ECaseResult {
  caseId: string
  passed: boolean
  error?: string
  status?: 'passed' | 'failed' | 'skipped_requires_browser'
  screenshot?: string
  evidence?: E2EEvidence
}

export interface E2EDiagnosis {
  diagnoses: Array<{
    case_id: string
    classification: 'expected_broken' | 'selector_coupled' | 'real_regression'
    reason: string
    evidence_refs: string[]
  }>
  counts: { expected_broken: number; selector_coupled: number; real_regression: number }
  rollback_case_ids: string[]
  manifest_present: boolean
  manifest_updates: { updated: string[] }
}

export interface RollbackEvent {
  from: string
  to: string
  reason: string
  failedCases?: E2ECaseResult[]
}

// ── 阶段 Phase ──
export type StagePhase = 'idle' | 'qa' | 'generating' | 'reviewing' | 'complete'

// ── Tool Trace ──
export interface ToolTraceEntry {
  id: string
  type: 'call' | 'result'
  tool: string
  args?: Record<string, any>
  status: 'running' | 'done' | 'error'
  summary?: string
  timestamp: number
}

// ── Graph Event Types 扩展 ──
export interface CompileErrorEntry {
  file: string
  line: number
  message: string
}

export interface AgentLogEntry {
  id: string
  type: 'thinking' | 'tool_call' | 'tool_result' | 'file_start'
       | 'file_complete' | 'compile' | 'phase_summary' | 'cancel' | 'feedback_summary'
  timestamp: number
  thinkingText?: string
  thinkingDone?: boolean
  toolName?: string
  toolArgs?: Record<string, any>
  toolStatus?: 'running' | 'done' | 'error'
  toolDetail?: string
  filePath?: string
  fileTotal?: number
  fileDone?: boolean
  compileOk?: boolean
  compileErrors?: CompileErrorEntry[]
  summary?: string
  // feedback_summary fields
  feedbackText?: string
  feedbackResult?: string
  feedbackExpanded?: boolean
}

export type GraphEventTypeExtended =
  | GraphEventType
  | 'manager_message'
  | 'doc_chunk'
  | 'prd_generate_start' | 'prd_generate_done'
  | 'design_gen_start' | 'design_gen_done'
  | 'code_gen_start' | 'code_gen_done'
  | 'file_start' | 'file_chunk' | 'file_complete'
  | 'tool_call' | 'tool_result'
  | 'e2e_cases_gen_start' | 'e2e_cases_gen_done'
  | 'e2e_execute_start' | 'e2e_case_start' | 'e2e_execute_done'
  | 'planner_start' | 'planner_dag' | 'planner_reflect'
  | 'task_start' | 'task_complete' | 'task_failed'
  | 'context_summarized' | 'contract_verify'
  | 'graph_complete'

// ── Planner/Executor Types ──

export interface PlannerTaskDef {
  id: string
  type: 'bootstrap' | 'business'
  description: string
  deps: string[]
  files: string[]
  contract: Record<string, any>
  status: 'pending' | 'running' | 'done' | 'failed'
  executorSummary?: string
  compileErrors?: CompileErrorEntry[]
}

export interface TaskGroup {
  taskId: string
  description: string
  files: string[]
  status: 'pending' | 'running' | 'done' | 'failed'
  entries: AgentLogEntry[]
  fileCount: number
  compileErrors: number
}

// HMR Event types from iframe
export interface HmrEvent {
  type: 'hot-replace' | 'hot-rerender' | 'warm-reload' | 'full-reload'
  file: string
  timestamp: number
}
