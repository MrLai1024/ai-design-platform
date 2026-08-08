// Tests: agent_message dialogue entries + planner_reflect status cards.
//
// agent messages are the model's own words (bubble entry, zero templating);
// planner_reflect is a system-status card whose text is rendered per decision
// by the FRONTEND — backend events carry only structured data.
import { describe, it, expect, vi, beforeEach } from 'vitest'

const mocks = vi.hoisted(() => {
  const entries: any[] = []
  const store = {
    agentLogEntries: entries,
    taskGroups: new Map(),
    setPlannerTasks: vi.fn(),
    setPlannerReasoning: vi.fn(),
    initFileTree: vi.fn(),
    addTaskLogEntry: vi.fn(),
    setCurrentTask: vi.fn(),
    updateTaskStatus: vi.fn(),
    finalizeFile: vi.fn(),
  }
  return { store }
})

vi.mock('@/stores/generation', () => ({
  useGenerationStore: () => mocks.store,
}))

import { handleCodeSSEEvent } from './useCodeStream'

beforeEach(() => {
  mocks.store.agentLogEntries.length = 0
  mocks.store.setPlannerTasks.mockClear()
  mocks.store.setPlannerReasoning.mockClear()
  mocks.store.addTaskLogEntry.mockClear()
})

describe('agent_message', () => {
  it('pushes a dialogue bubble entry with the model text verbatim', () => {
    handleCodeSSEEvent({ _t: 'agent_message', text: '已完成 App.vue，编译通过', task_id: 'task-0' })
    const entry = mocks.store.agentLogEntries.at(-1)
    expect(entry.type).toBe('agent_message')
    expect(entry.agentMessage).toBe('已完成 App.vue，编译通过')
  })

  it('routes the entry into the task group when task_id is present', () => {
    handleCodeSSEEvent({ _t: 'agent_message', text: 'hello', task_id: 'task-3' })
    const entry = mocks.store.agentLogEntries.at(-1)
    expect(mocks.store.addTaskLogEntry).toHaveBeenCalledWith('task-3', entry)
  })

  it('drops empty text entries', () => {
    handleCodeSSEEvent({ _t: 'agent_message', text: '' })
    const entry = mocks.store.agentLogEntries.at(-1)
    expect(entry.agentMessage).toBe('')
  })
})

describe('planner_reflect status cards (frontend-rendered text)', () => {
  it('renders replan_missing_files with the missing count', () => {
    handleCodeSSEEvent({ _t: 'planner_reflect', decision: 'replan_missing_files', missing_files: ['a', 'b'] })
    expect(mocks.store.agentLogEntries.at(-1).summary).toContain('增量重规划')
    expect(mocks.store.agentLogEntries.at(-1).summary).toContain('2')
  })

  it('renders no_changes verdict', () => {
    handleCodeSSEEvent({ _t: 'planner_reflect', decision: 'no_changes' })
    expect(mocks.store.agentLogEntries.at(-1).summary).toContain('无需修改')
  })

  it('renders final_compile_repair with fix file count', () => {
    handleCodeSSEEvent({ _t: 'planner_reflect', decision: 'final_compile_repair', fix_files: ['src/App.vue'] })
    expect(mocks.store.agentLogEntries.at(-1).summary).toContain('修复')
  })

  it('renders final_compile_abort with the diagnostic reason', () => {
    handleCodeSSEEvent({ _t: 'planner_reflect', decision: 'final_compile_abort', reason: '超过最大修复轮次' })
    expect(mocks.store.agentLogEntries.at(-1).summary).toContain('超过最大修复轮次')
  })

  it('renders needs_feedback with the error count as a continuing exit', () => {
    handleCodeSSEEvent({ _t: 'planner_reflect', decision: 'needs_feedback', error_count: 3 })
    expect(mocks.store.agentLogEntries.at(-1).summary).toContain('3 个错误')
    expect(mocks.store.agentLogEntries.at(-1).summary).toContain('继续')
  })

  it('unknown decision falls back to the raw key', () => {
    handleCodeSSEEvent({ _t: 'planner_reflect', decision: 'some_new_decision' })
    expect(mocks.store.agentLogEntries.at(-1).summary).toContain('some_new_decision')
  })

  it('never leaks backend message fields into the card', () => {
    handleCodeSSEEvent({ _t: 'planner_reflect', decision: 'replan_missing_files', missing_files: ['a'] })
    expect(mocks.store.agentLogEntries.at(-1).summary).not.toContain('Planner 决策')
  })
})

describe('planner_dag reasoning', () => {
  it('keeps the visible planner analysis when reasoning is absent', () => {
    handleCodeSSEEvent({ _t: 'planner_dag', tasks: [{ id: 'task-fix-0' }] })
    expect(mocks.store.setPlannerTasks).toHaveBeenCalled()
    expect(mocks.store.setPlannerReasoning).not.toHaveBeenCalled()
  })

  it('updates reasoning when the model provides it', () => {
    handleCodeSSEEvent({ _t: 'planner_dag', tasks: [], reasoning: '模型分析' })
    expect(mocks.store.setPlannerReasoning).toHaveBeenCalledWith('模型分析')
  })
})
