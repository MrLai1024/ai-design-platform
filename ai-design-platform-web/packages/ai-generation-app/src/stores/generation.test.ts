// Tests: planner task view merge semantics.
//
// Incremental replans and the final-compile repair loop emit planner_dag with
// ONLY the delta tasks. setPlannerTasks must MERGE (keep earlier tasks and
// their log history) — a full reset wiped the visible AgentLog task cards,
// making a run look like "only 2 files were generated".
import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useGenerationStore } from './generation'

function task(id: string, files: string[], status = 'pending' as const, type = 'business' as const) {
  return { id, description: id, files, status, type, deps: [], contract: {} }
}

describe('setPlannerTasks merge semantics', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('keeps earlier tasks and their log history on incremental replan', () => {
    const s = useGenerationStore()
    s.setPlannerTasks([task('task-0', ['src/main.js'], 'done', 'bootstrap')])

    // simulate log entries accumulated on the earlier task
    s.addTaskLogEntry('task-0', { id: 'e1', type: 'agent_message', timestamp: 1, agentMessage: 'hi' })
    s.addTaskLogEntry('task-0', { id: 'e2', type: 'file_start', timestamp: 2, filePath: 'src/main.js' })

    // incremental replan emits ONLY the delta tasks
    s.setPlannerTasks([task('task-fallback-0', ['src/App.vue'])])

    const ids = s.plannerTasks.map(t => t.id)
    expect(ids).toContain('task-0')
    expect(ids).toContain('task-fallback-0')
    // history preserved on the earlier group
    expect(s.taskGroups.get('task-0')?.entries.length).toBe(2)
    expect(s.taskGroups.get('task-0')?.entries[0]?.agentMessage).toBe('hi')
    // the new task starts empty
    expect(s.taskGroups.get('task-fallback-0')?.entries.length).toBe(0)
  })

  it('updates an existing task in place without losing its entries', () => {
    const s = useGenerationStore()
    s.setPlannerTasks([task('task-0', ['src/main.js'], 'pending')])
    s.addTaskLogEntry('task-0', { id: 'e1', type: 'compile', timestamp: 1, compileOk: false, compileErrors: [{ file: 'a', line: 1, column: 1, message: 'x', source: 'esbuild' }] })

    s.setPlannerTasks([task('task-0', ['src/main.js'], 'done')])

    expect(s.plannerTasks.length).toBe(1)
    expect(s.plannerTasks[0]!.status).toBe('done')
    expect(s.taskGroups.get('task-0')?.entries.length).toBe(1)
  })
})
