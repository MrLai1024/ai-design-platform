// src/stores/generation.ts
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { ChatMessage, FileEntry, ComponentLibrary, Stage, StageStatus, StageOutputs, CodeViewTab, RightPanelView, StepNode, E2ETestCase, E2ECaseResult, RollbackEvent } from '@/types/generation'
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
    resetAll,
  }
})
