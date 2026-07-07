import { useState, useCallback, useRef } from 'react';
import { useAppSelector, useAppDispatch } from '../store';
import { setIsRunning, setNodeStatus, resetNodeStatuses, appendRunLog } from '../store/slices/workflowSlice';
import type { WorkflowEvent } from '../types/workflow';

const API_BASE = '/api/v1/workflow';

export function useWorkflowRun() {
  const dispatch = useAppDispatch();
  const isRunning = useAppSelector(s => s.workflow.isRunning);
  const currentWorkflow = useAppSelector(s => s.workflow.currentWorkflow);
  const [humanConfirm, setHumanConfirm] = useState<{
    nodeId: string; message: string;
    fields: Array<{ key: string; label: string; type: string }>;
  } | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);

  const handleEvent = useCallback((event: WorkflowEvent) => {
    switch (event.event_type) {
      case 'workflow_start':
        dispatch(appendRunLog('🚀 工作流开始执行'));
        break;
      case 'stage_start':
        dispatch(setNodeStatus({ nodeId: event.stage, status: 'running' }));
        dispatch(appendRunLog(`▶ ${event.data.label || event.stage} 开始执行...`));
        break;
      case 'stage_complete':
        dispatch(setNodeStatus({ nodeId: event.stage, status: 'done' }));
        dispatch(appendRunLog(`✅ ${event.data.label || event.stage} 完成`));
        break;
      case 'human_confirm_required':
        setHumanConfirm({
          nodeId: event.stage,
          message: event.data.message as string,
          fields: event.data.fields as Array<{ key: string; label: string; type: string }>,
        });
        dispatch(appendRunLog(`⏳ 等待确认: ${event.stage}`));
        break;
      case 'node_error':
        if (event.stage) dispatch(setNodeStatus({ nodeId: event.stage, status: 'error' }));
        dispatch(appendRunLog(`❌ 错误: ${event.data.error || 'unknown'}`));
        break;
      case 'workflow_complete':
        dispatch(appendRunLog('🏁 工作流完成'));
        dispatch(setIsRunning(false));
        eventSourceRef.current?.close();
        break;
    }
  }, [dispatch]);

  const startRun = useCallback(async () => {
    if (!currentWorkflow) return;
    // Save first
    await fetch(`${API_BASE}/save`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(currentWorkflow),
    });
    dispatch(setIsRunning(true));
    dispatch(resetNodeStatuses());
    dispatch(appendRunLog(''));

    // Use fetch for SSE (EventSource doesn't support POST)
    const url = `${API_BASE}/${currentWorkflow.id}/run`;
    try {
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      const reader = res.body?.getReader();
      const decoder = new TextDecoder();
      if (!reader) return;

      let buffer = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        // Parse SSE data lines
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const event: WorkflowEvent = JSON.parse(line.slice(6));
              handleEvent(event);
            } catch {}
          }
        }
      }
    } catch (err) {
      dispatch(appendRunLog(`❌ 连接失败: ${String(err)}`));
      dispatch(setIsRunning(false));
    }
  }, [currentWorkflow, dispatch, handleEvent]);

  const submitHumanConfirm = useCallback(async (response: Record<string, unknown>) => {
    if (!currentWorkflow || !humanConfirm) return;
    setHumanConfirm(null);
    try {
      await fetch(`${API_BASE}/${currentWorkflow.id}/resume`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(response),
      });
    } catch (err) {
      console.error('Failed to submit:', err);
    }
  }, [currentWorkflow, humanConfirm]);

  const cancelRun = useCallback(() => {
    eventSourceRef.current?.close();
    dispatch(setIsRunning(false));
    dispatch(resetNodeStatuses());
    setHumanConfirm(null);
  }, [dispatch]);

  return { isRunning, humanConfirm, startRun, submitHumanConfirm, cancelRun };
}
