// src/stores/generation.ts
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { ChatMessage, FileEntry, ComponentLibrary, Stage, StageStatus, StageOutputs, CodeViewTab, RightPanelView, StepNode, E2ETestCase, E2ECaseResult, RollbackEvent, StagePhase, ToolTraceEntry, ReviewAgentState, ReviewFinding } from '@/types/generation'
import type { RequirementsState, AnalysisPanelMode, AnalysisMode } from '@/types/requirements'

export const useGenerationStore = defineStore('generation', () => {
  // ── State ──
  const messages = ref<ChatMessage[]>([])
  const files = ref<Map<string, FileEntry>>(new Map())
  const activeFile = ref<string | null>(null)
  const isStreaming = ref(false)
  const compiledOutput = ref<string>('')
  const compileError = ref<string | null>(null)
  const currentLib = ref<ComponentLibrary>('tailwind')

  // ── 多智能体阶段状态 ──
  const stage = ref<Stage>('idle')
  const stageStatus = ref<Record<string, StageStatus>>({
    analysis: 'pending',
    design: 'pending',
    code: 'pending',
    review: 'pending',
    e2e: 'pending',
  })
  const stageOutputs = ref<StageOutputs>({
    analysis: null,
    design: null,
    code: null,
    review: null,
    e2e: null,
  })
  const codeViewTab = ref<CodeViewTab>('preview')
  const rightPanelView = ref<RightPanelView>('preview')

  // ── E2E & 回滚 & 审核 ──
  const e2eTestCases = ref<E2ETestCase[]>([])
  const e2eResults = ref<E2ECaseResult[]>([])
  const e2eRunning = ref(false)
  const rollbackEvents = ref<RollbackEvent[]>([])
  const needsManualReview = ref(false)
  const loopBreakReason = ref<string | null>(null)
  const currentGenerationId = ref<string | null>(null)

  // ── 需求分析面板状态 ──
  const requirementsState = ref<RequirementsState | null>(null)
  const analysisPanelMode = ref<AnalysisPanelMode>('prd')
  const prdStreamingContent = ref('')
  const prdCurrentSection = ref<string | null>(null)
  const prdVersion = ref(0)

  // ── 阶段控制 ──
  const stagePhase = ref<StagePhase>('idle')
  const awaitingConfirm = ref(false)

  // ── 流式文档（analysis/design/e2e-testcases 共享）──
  const docStreamingContent = ref('')
  const docIsStreaming = ref(false)

  // ── Code 阶段 ──
  const generatedFiles = ref<Record<string, string>>({})
  const currentGeneratingFile = ref<string | null>(null)
  const toolTraces = ref<ToolTraceEntry[]>([])

  // ── Review 阶段 ──
  const reviewAgents = ref<ReviewAgentState[]>([])
  const reviewReportHtml = ref<string | null>(null)

  // ── E2E 阶段 ──
  const e2eTestCasesMd = ref<string | null>(null)
  const e2eUserConfirmed = ref(false)
  const e2eCurrentCaseId = ref<string | null>(null)

  // ── Getters ──
  const lastAssistantMessage = computed(() => {
    for (let i = messages.value.length - 1; i >= 0; i--) {
      if (messages.value[i]!.role === 'assistant') return messages.value[i]!
    }
    return null
  })

  const dirtyFiles = computed(() => {
    const dirty = new Set<string>()
    for (const [name, entry] of files.value) {
      if (entry.isDirty) dirty.add(name)
    }
    return dirty
  })

  const fileList = computed(() => Array.from(files.value.values()))

  const activeFileEntry = computed(() => {
    if (!activeFile.value) return null
    return files.value.get(activeFile.value) ?? null
  })

  const currentStepNodes = computed<StepNode[]>(() => {
    const stages: Array<{ key: Stage; label: string }> = [
      { key: 'analysis', label: '需求分析' },
      { key: 'design', label: '方案设计' },
      { key: 'code', label: '功能开发' },
      { key: 'review', label: '质量校验' },
      { key: 'e2e', label: 'E2E验证' },
    ]
    return stages.map((s) => ({
      key: s.key,
      label: s.label,
      status: stageStatus.value[s.key] as StageStatus,
    }))
  })

  const isStageDone = computed(() => (s: Stage) => {
    return stageStatus.value[s] === 'done'
  })

  const showStreamDocument = computed(() => {
    if (stage.value === 'analysis' || stage.value === 'design') return true
    if (stage.value === 'e2e' && !e2eUserConfirmed.value) return true
    return false
  })

  const showNextButton = computed(() =>
    awaitingConfirm.value && stagePhase.value === 'complete'
  )

  const reviewIssueSummary = computed(() => {
    const all = reviewAgents.value.flatMap(a => a.findings)
    return {
      total: all.length,
      critical: all.filter(i => i.severity === 'critical').length,
      high: all.filter(i => i.severity === 'high').length,
    }
  })

  const compileStatus = computed(() => {
    const compiles = toolTraces.value.filter(t => t.tool === 'compile_project')
    const last = compiles.at(-1)
    return {
      hasErrors: last?.status === 'error',
      lastCompileOk: last?.status === 'done',
    }
  })

  // ── Actions ──
  function addMessage(msg: ChatMessage): void {
    messages.value.push(msg)
  }

  function appendToLastMessage(content: string): void {
    const last = messages.value[messages.value.length - 1]
    if (last && last.role === 'assistant') {
      last.content += content
    } else if (import.meta.env.DEV) {
      console.warn('[generation] appendToLastMessage: last message is not from assistant')
    }
  }

  function appendReasoning(text: string): void {
    const last = messages.value[messages.value.length - 1]
    if (last && last.role === 'assistant') {
      if (!last.reasoningContent) last.reasoningContent = ''
      last.reasoningContent += text
    }
  }

  function finishReasoning(): void {
    const last = messages.value[messages.value.length - 1]
    if (last && last.role === 'assistant') {
      last.reasoningDurationMs = Date.now() - (last.timestamp || Date.now())
    }
  }

  function finalizeLastMessage(): void {
    const last = messages.value[messages.value.length - 1]
    if (last && last.role === 'assistant') {
      last.isStreaming = false
    }
    isStreaming.value = false
  }

  function setFile(filename: string, entry: FileEntry): void {
    files.value.set(filename, entry)
    if (!activeFile.value) {
      activeFile.value = filename
    }
  }

  function updateFileContent(filename: string, content: string): void {
    const entry = files.value.get(filename)
    if (entry) {
      entry.content = content
      entry.isDirty = true
    } else if (import.meta.env.DEV) {
      console.warn(`[generation] updateFileContent: file "${filename}" not found`)
    }
  }

  function setActiveFile(filename: string): void {
    if (files.value.has(filename)) {
      activeFile.value = filename
    } else if (import.meta.env.DEV) {
      console.warn(`[generation] setActiveFile: file "${filename}" not found`)
    }
  }

  function removeFile(filename: string): void {
    files.value.delete(filename)
    if (activeFile.value === filename) {
      activeFile.value = fileList.value[0]?.filename ?? null
    }
  }

  function addNewFile(filename: string): void {
    if (files.value.has(filename)) {
      console.warn(`[generation] addNewFile: file "${filename}" already exists, overwriting`)
    }
    const entry: FileEntry = {
      filename,
      content: '',
      language: 'vue',
      isDirty: false,
      source: 'user',
    }
    files.value.set(filename, entry)
    activeFile.value = filename
  }

  function markFileClean(filename: string): void {
    const entry = files.value.get(filename)
    if (entry) {
      entry.isDirty = false
    } else if (import.meta.env.DEV) {
      console.warn(`[generation] markFileClean: file "${filename}" not found`)
    }
  }

  function setCompiledOutput(output: string): void {
    compiledOutput.value = output
  }

  function setCompileError(error: string | null): void {
    compileError.value = error
  }

  function setCurrentLib(lib: ComponentLibrary): void {
    currentLib.value = lib
  }

  function setStage(s: Stage): void {
    stage.value = s
  }

  function setStageStatus(key: string, status: StageStatus): void {
    stageStatus.value[key] = status
  }

  function setStageOutput(stageKey: string, content: string): void {
    if (stageKey in stageOutputs.value) {
      ;(stageOutputs.value as Record<string, string | null>)[stageKey] = content
    } else if (import.meta.env.DEV) {
      console.warn(`[generation] setStageOutput: unknown stage key "${stageKey}"`)
    }
  }

  function setCodeViewTab(tab: CodeViewTab): void {
    codeViewTab.value = tab
    rightPanelView.value = tab
  }

  function setRightPanelView(view: RightPanelView): void {
    rightPanelView.value = view
  }

  function enterCodeStage(): void {
    stage.value = 'code'
    stageStatus.value.code = 'active'
    rightPanelView.value = 'preview'
    codeViewTab.value = 'preview'
  }

  function completeCurrentStage(): void {
    const current = stage.value
    if (current && current !== 'idle') {
      stageStatus.value[current] = 'done'
    }
  }

  // ── E2E & 回滚 Actions ──
  function setE2ETestCases(cases: E2ETestCase[]): void {
    e2eTestCases.value = cases
  }
  function addE2EResult(result: E2ECaseResult): void {
    e2eResults.value.push(result)
  }
  function clearE2EResults(): void {
    e2eResults.value = []
    e2eRunning.value = false
  }
  function addRollbackEvent(event: RollbackEvent): void {
    rollbackEvents.value.push(event)
  }
  function setNeedsManualReview(needs: boolean): void {
    needsManualReview.value = needs
  }
  function setLoopBreakReason(reason: string | null): void {
    loopBreakReason.value = reason
  }
  function setGenerationId(id: string): void {
    currentGenerationId.value = id
  }

  // ── 需求分析 Actions ──

  function setRequirementsState(s: RequirementsState): void {
    requirementsState.value = s
  }

  function patchRequirementsState(fields: Partial<RequirementsState>): void {
    if (!requirementsState.value) {
      requirementsState.value = fields as RequirementsState
    } else {
      Object.assign(requirementsState.value, fields)
    }
  }

  function setAnalysisPanelMode(mode: AnalysisPanelMode): void {
    analysisPanelMode.value = mode
  }

  function appendPRDContent(content: string): void {
    prdStreamingContent.value += content
  }

  function appendPRDDiff(change: string, section: string, content: string): void {
    const prefix = change === 'added' ? '\n\n🆕 **新增** ' : change === 'modified' ? '\n\n✏️ **修改** ' : '\n\n'
    prdStreamingContent.value += `${prefix}${section}: ${content}`
  }

  function setPRDCurrentSection(section: string | null): void {
    prdCurrentSection.value = section
  }

  function setPRDComplete(fullContent: string): void {
    prdStreamingContent.value = fullContent
  }

  function setPRDVersion(version: number): void {
    prdVersion.value = version
  }

  // ── 阶段 Phase Actions ──
  function setStagePhase(phase: StagePhase): void {
    stagePhase.value = phase
  }
  function setAwaitingConfirm(v: boolean): void {
    awaitingConfirm.value = v
  }

  // ── 流式文档 Actions ──
  function appendDocContent(content: string): void {
    docStreamingContent.value += content
  }
  function setDocComplete(fullContent: string): void {
    docStreamingContent.value = fullContent
    docIsStreaming.value = false
  }
  function resetDocContent(): void {
    docStreamingContent.value = ''
    docIsStreaming.value = true
  }

  // ── Code 阶段 Actions ──
  function initFileTree(files: string[]): void {
    generatedFiles.value = {}
    for (const f of files) {
      generatedFiles.value[f] = ''
    }
    toolTraces.value = []
  }
  function setCurrentGeneratingFile(path: string | null): void {
    currentGeneratingFile.value = path
  }
  function appendFileContent(path: string, content: string): void {
    if (!generatedFiles.value[path]) {
      generatedFiles.value[path] = ''
    }
    generatedFiles.value[path] += content
  }
  function finalizeFile(path: string): void {
    setFile(path, {
      filename: path,
      content: generatedFiles.value[path] || '',
      language: path.endsWith('.vue') ? 'vue' : path.endsWith('.ts') ? 'typescript' : 'javascript',
      isDirty: false,
      source: 'ai',
    })
  }
  function addToolTrace(entry: Omit<ToolTraceEntry, 'id' | 'timestamp'>): string {
    const id = Date.now().toString(36) + Math.random().toString(36).slice(2, 7)
    toolTraces.value.push({ ...entry, id, timestamp: Date.now() })
    return id
  }
  function updateToolTrace(id: string, patch: Partial<ToolTraceEntry>): void {
    const idx = toolTraces.value.findIndex(t => t.id === id)
    if (idx >= 0) Object.assign(toolTraces.value[idx]!, patch)
  }
  function setCodeGenDone(_files: number, _errors: number): void {
    // compile status tracked via compileStatus computed
  }

  // ── Review 阶段 Actions ──
  function initReviewAgents(agents: Array<{ key: string; name: string; icon: string }>): void {
    reviewAgents.value = agents.map(a => ({
      key: a.key,
      name: a.name,
      icon: a.icon,
      status: 'pending' as const,
      findings: [],
      totalIssues: 0,
    }))
  }
  function appendAgentFinding(agentKey: string, issue: ReviewFinding): void {
    const agent = reviewAgents.value.find(a => a.key === agentKey)
    if (agent) {
      agent.findings.push(issue)
      agent.totalIssues = agent.findings.length
    }
  }
  function setAgentDone(agentKey: string): void {
    const agent = reviewAgents.value.find(a => a.key === agentKey)
    if (agent) agent.status = 'done'
  }
  function setAgentRunning(agentKey: string): void {
    const agent = reviewAgents.value.find(a => a.key === agentKey)
    if (agent) agent.status = 'running'
  }

  // ── E2E 阶段 Actions ──
  function setE2ECasesDoc(md: string): void {
    e2eTestCasesMd.value = md
  }
  function confirmE2ECases(): void {
    e2eUserConfirmed.value = true
  }
  function setCurrentE2ECase(caseId: string): void {
    e2eCurrentCaseId.value = caseId
  }
  function setE2EComplete(_summary: { total: number; passed: number; failed: number }): void {
    // handled by existing e2e logic
  }

  function resetAll(): void {
    messages.value = []
    files.value = new Map()
    activeFile.value = null
    isStreaming.value = false
    compiledOutput.value = ''
    compileError.value = null
    stage.value = 'idle'
    stageStatus.value = { analysis: 'pending', design: 'pending', code: 'pending', review: 'pending', e2e: 'pending' }
    stageOutputs.value = { analysis: null, design: null, code: null, review: null, e2e: null }
    codeViewTab.value = 'preview'
    rightPanelView.value = 'preview'
    // E2E & 回滚 & 审核
    e2eTestCases.value = []
    e2eResults.value = []
    e2eRunning.value = false
    rollbackEvents.value = []
    needsManualReview.value = false
    loopBreakReason.value = null
    currentGenerationId.value = null
    requirementsState.value = null
    analysisPanelMode.value = 'prd'
    prdStreamingContent.value = ''
    prdCurrentSection.value = null
    prdVersion.value = 0
    stagePhase.value = 'idle'
    awaitingConfirm.value = false
    docStreamingContent.value = ''
    docIsStreaming.value = false
    generatedFiles.value = {}
    currentGeneratingFile.value = null
    toolTraces.value = []
    reviewAgents.value = []
    reviewReportHtml.value = null
    e2eTestCasesMd.value = null
    e2eUserConfirmed.value = false
    e2eCurrentCaseId.value = null
  }

  return {
    // state
    messages, files, activeFile, isStreaming, compiledOutput, compileError, currentLib,
    stage, stageStatus, stageOutputs, codeViewTab, rightPanelView,
    e2eTestCases, e2eResults, e2eRunning, rollbackEvents, needsManualReview, loopBreakReason, currentGenerationId,
    // 需求分析
    requirementsState, analysisPanelMode, prdStreamingContent, prdCurrentSection, prdVersion,
    // getters
    lastAssistantMessage, dirtyFiles, fileList, activeFileEntry,
    currentStepNodes, isStageDone,
    // actions
    addMessage, appendToLastMessage, appendReasoning, finishReasoning, finalizeLastMessage,
    setFile, updateFileContent, setActiveFile, removeFile, addNewFile,
    markFileClean, setCompiledOutput, setCompileError, setCurrentLib,
    setStage, setStageStatus, setStageOutput, setCodeViewTab, setRightPanelView,
    enterCodeStage, completeCurrentStage,
    setE2ETestCases, addE2EResult, clearE2EResults, addRollbackEvent, setNeedsManualReview, setLoopBreakReason, setGenerationId,
    setRequirementsState, patchRequirementsState, setAnalysisPanelMode,
    appendPRDContent, appendPRDDiff, setPRDCurrentSection, setPRDComplete, setPRDVersion,
    // 阶段控制
    stagePhase, awaitingConfirm,
    setStagePhase, setAwaitingConfirm,
    // 流式文档
    docStreamingContent, docIsStreaming,
    appendDocContent, setDocComplete, resetDocContent,
    // Code 阶段
    generatedFiles, currentGeneratingFile, toolTraces,
    initFileTree, setCurrentGeneratingFile, appendFileContent, finalizeFile,
    addToolTrace, updateToolTrace, setCodeGenDone,
    // Review 阶段
    reviewAgents, reviewReportHtml,
    initReviewAgents, appendAgentFinding, setAgentDone, setAgentRunning,
    // E2E 阶段
    e2eTestCasesMd, e2eUserConfirmed, e2eCurrentCaseId,
    setE2ECasesDoc, confirmE2ECases, setCurrentE2ECase, setE2EComplete,
    // Computed
    showStreamDocument, showNextButton, reviewIssueSummary, compileStatus,
    resetAll,
  }
})
