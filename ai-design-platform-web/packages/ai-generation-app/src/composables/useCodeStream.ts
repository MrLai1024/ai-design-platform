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
      // reasoning is model speech — only update when present (an empty
      // incremental delta must not wipe the planner's visible analysis)
      if (event.reasoning) s.setPlannerReasoning(event.reasoning)
      s.agentLogEntries.push({
        id: entryId(), type: 'phase_summary', timestamp: Date.now(),
        summary: `任务拆解完成：${tasks.length} 个任务`,
        fileTotal: tasks.length,
      })
      break
    }

    case 'planner_reflect': {
      // System-status card — UI text rendered per decision, never backend
      // speech. Backend events carry only structured data (zero voice).
      const LABELS: Record<string, string> = {
        done: '所有任务完成，编译通过',
        replan_missing_files: `增量重规划：缺 ${event.missing_files?.length || 0} 个文件`,
        final_compile_replan: `最终编译修复：重规划 ${event.missing_files?.length || 0} 个缺失文件`,
        final_compile_repair: `最终编译修复：修复 ${event.fix_files?.length || 0} 个文件`,
        final_compile_abort: `最终编译修复中止：${event.reason || '无法继续'}`,
        no_changes: '检查完毕，无需修改',
        has_failures: '存在失败任务，准备重试',
        needs_feedback: `仍有 ${event.error_count || 0} 个错误未解决，可在下方输入修改意见让 agent 继续完善`,
      }
      s.agentLogEntries.push({
        id: entryId(), type: 'phase_summary', timestamp: Date.now(),
        summary: LABELS[event.decision] || `Planner 决策: ${event.decision}`,
      })
      break
    }

    case 'agent_message': {
      const entry: AgentLogEntry = {
        id: entryId(), type: 'agent_message', timestamp: Date.now(),
        agentMessage: event.text || '',
      }
      s.agentLogEntries.push(entry)
      if (event.task_id) s.addTaskLogEntry(event.task_id, entry)
      break
    }

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
