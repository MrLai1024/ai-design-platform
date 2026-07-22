// src/composables/useCodeStream.ts
import { useGenerationStore } from '@/stores/generation'
import type { AgentLogEntry } from '@/types/generation'

let _store: ReturnType<typeof useGenerationStore> | null = null

function store() {
  if (!_store) _store = useGenerationStore()
  return _store
}

function entryId(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 7)
}

function findLastRunningToolCall(entries: AgentLogEntry[], tool: string): AgentLogEntry | undefined {
  for (let i = entries.length - 1; i >= 0; i--) {
    const e = entries[i]!
    if (e.type === 'tool_call' && e.toolName === tool && e.toolStatus === 'running') {
      return e
    }
  }
  return undefined
}

export function handleCodeSSEEvent(event: any): void {
  const s = store()
  const t = event._t

  switch (t) {
    case 'code_gen_start':
      s.agentLogEntries.push({
        id: entryId(), type: 'phase_summary', timestamp: Date.now(),
        fileTotal: event.files?.length,
        summary: `开始生成 ${event.files?.length || 0} 个文件`,
      })
      s.initFileTree(event.files || [])
      break

    case 'thinking_chunk': {
      const last = s.agentLogEntries.at(-1)
      if (last?.type === 'thinking' && !last.thinkingDone) {
        last.thinkingText = (last.thinkingText || '') + (event.text || '')
      } else {
        s.agentLogEntries.push({
          id: entryId(), type: 'thinking', timestamp: Date.now(),
          thinkingText: event.text || '',
        })
      }
      break
    }

    case 'tool_call':
      s.agentLogEntries.push({
        id: entryId(), type: 'tool_call', timestamp: Date.now(),
        toolName: event.tool, toolArgs: event.args, toolStatus: 'running',
      })
      break

    case 'tool_result': {
      const running = findLastRunningToolCall(s.agentLogEntries, event.tool)
      if (running) {
        running.toolStatus = event.ok ? 'done' : 'error'
        running.toolDetail = event.detail?.path
          ? `→ ${event.detail.path}`
          : (event.ok ? 'Done' : 'Failed')
      }
      break
    }

    case 'file_start':
      s.agentLogEntries.push({
        id: entryId(), type: 'file_start', timestamp: Date.now(),
        filePath: event.path,
      })
      s.setCurrentGeneratingFile(event.path)
      // Clear content on new file start to prevent duplication
      if (s.generatedFiles[event.path]) s.generatedFiles[event.path] = ''
      break

    case 'file_chunk':
      s.appendFileContent(event.path, event.content || '')
      break

    case 'file_complete': {
      const entries = s.agentLogEntries
      let fileEntry: AgentLogEntry | undefined
      for (let i = entries.length - 1; i >= 0; i--) {
        if (entries[i]!.type === 'file_start' && entries[i]!.filePath === event.path) {
          fileEntry = entries[i]
          break
        }
      }
      if (fileEntry) fileEntry.fileDone = true
      s.finalizeFile(event.path)
      break
    }

    case 'compile_status':
      s.agentLogEntries.push({
        id: entryId(), type: 'compile', timestamp: Date.now(),
        compileOk: event.ok,
        compileErrors: event.errors || [],
      })
      break

    case 'code_gen_done':
      s.agentLogEntries.push({
        id: entryId(), type: 'phase_summary', timestamp: Date.now(),
        summary: `生成完成：${event.total_files || 0} 个文件，${event.compile_errors || 0} 个错误`,
        fileTotal: event.total_files,
      })
      break
  }
}
