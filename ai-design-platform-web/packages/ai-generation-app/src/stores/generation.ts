// src/stores/generation.ts
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { ChatMessage, FileEntry, ComponentLibrary, Stage, StageStatus, StageOutputs, CodeViewTab, RightPanelView, StepNode } from '@/types/generation'

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
  })
  const stageOutputs = ref<StageOutputs>({
    analysis: null,
    design: null,
  })
  const codeViewTab = ref<CodeViewTab>('preview')
  const rightPanelView = ref<RightPanelView>('preview')

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
    const stages: Array<{ key: 'analysis' | 'design' | 'code'; label: string }> = [
      { key: 'analysis', label: '需求分析' },
      { key: 'design', label: '详细设计' },
      { key: 'code', label: '代码实现' },
    ]
    return stages.map((s) => ({
      key: s.key,
      label: s.label,
      status: stageStatus.value[s.key] as StageStatus,
    }))
  })

  const isStageDone = computed(() => (s: 'analysis' | 'design' | 'code') => {
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

  function setStageOutput(stageKey: 'analysis' | 'design', content: string): void {
    stageOutputs.value[stageKey] = content
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
    if (current === 'analysis' || current === 'design') {
      stageStatus.value[current] = 'done'
    }
  }

  function resetAll(): void {
    messages.value = []
    files.value = new Map()
    activeFile.value = null
    isStreaming.value = false
    compiledOutput.value = ''
    compileError.value = null
    stage.value = 'idle'
    stageStatus.value = { analysis: 'pending', design: 'pending', code: 'pending' }
    stageOutputs.value = { analysis: null, design: null }
    codeViewTab.value = 'preview'
    rightPanelView.value = 'preview'
  }

  return {
    // state
    messages, files, activeFile, isStreaming, compiledOutput, compileError, currentLib,
    stage, stageStatus, stageOutputs, codeViewTab, rightPanelView,
    // getters
    lastAssistantMessage, dirtyFiles, fileList, activeFileEntry,
    currentStepNodes, isStageDone,
    // actions
    addMessage, appendToLastMessage, finalizeLastMessage,
    setFile, updateFileContent, setActiveFile, removeFile, addNewFile,
    markFileClean, setCompiledOutput, setCompileError, setCurrentLib,
    setStage, setStageStatus, setStageOutput, setCodeViewTab, setRightPanelView,
    enterCodeStage, completeCurrentStage,
    resetAll,
  }
})
