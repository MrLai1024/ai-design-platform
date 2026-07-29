// src/composables/useCodeStream.ts
import { useGenerationStore } from '@/stores/generation'
import type { AgentLogEntry, PlannerTaskDef } from '@/types/generation'

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
      if (event.task_id) {
        const entry = s.agentLogEntries.at(-1)
        if (entry) s.addTaskLogEntry(event.task_id, entry)
      }
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
      if (event.task_id) {
        const entry = s.agentLogEntries.at(-1)
        if (entry) s.addTaskLogEntry(event.task_id, entry)
      }
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
      if (event.task_id) {
        const entry = s.agentLogEntries.at(-1)
        if (entry) s.addTaskLogEntry(event.task_id, entry)
      }
      break

    case 'code_gen_done':
      s.agentLogEntries.push({
        id: entryId(), type: 'phase_summary', timestamp: Date.now(),
        summary: `生成完成：${event.total_files || 0} 个文件，${event.compile_errors || 0} 个错误`,
        fileTotal: event.total_files,
      })
      break

    case 'planner_start':
      s.agentLogEntries.push({
        id: entryId(), type: 'phase_summary', timestamp: Date.now(),
        summary: event.message || 'Planner 正在分析设计方案...',
      })
      break

    case 'planner_dag': {
      const tasks: PlannerTaskDef[] = (event.tasks || []).map((t: any) => ({
        ...t,
        status: t.status || 'pending',
      }))
      s.setPlannerTasks(tasks)
      s.setPlannerReasoning(event.reasoning || '')
      s.agentLogEntries.push({
        id: entryId(), type: 'phase_summary', timestamp: Date.now(),
        summary: `任务拆解完成：${tasks.length} 个任务`,
        fileTotal: tasks.length,
      })
      break
    }

    case 'planner_reflect':
      s.agentLogEntries.push({
        id: entryId(), type: 'phase_summary', timestamp: Date.now(),
        summary: `Planner 决策: ${event.decision} — ${event.reason || ''}`,
      })
      break

    case 'task_start':
      s.setCurrentTask(event.task_id)
      s.updateTaskStatus(event.task_id, 'running')
      break

    case 'task_complete':
      s.updateTaskStatus(event.task_id, event.compile_errors === 0 ? 'done' : 'failed')
      break

    case 'task_failed':
      s.updateTaskStatus(event.task_id, 'failed')
      break
  }
}
