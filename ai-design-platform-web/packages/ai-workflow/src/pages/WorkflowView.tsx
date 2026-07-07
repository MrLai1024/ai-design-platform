import React, { useCallback, useEffect } from 'react';
import { WorkflowCanvas } from '../components/WorkflowCanvas';
import { WorkflowToolbar } from '../components/WorkflowToolbar';
import { NodePalette } from '../components/panels/NodePalette';
import { NodeConfigPanel } from '../components/panels/NodeConfigPanel';
import { RunOverlay } from '../components/panels/RunOverlay';
import { useWorkflow } from '../composables/useWorkflow';
import { useWorkflowRun } from '../composables/useWorkflowRun';
import { useAppDispatch, useAppSelector } from '../store';
import { setCurrentWorkflow } from '../store/slices/workflowSlice';
import type { WorkflowIR } from '../types/workflow';

export function WorkflowView() {
  const dispatch = useAppDispatch();
  const isRunning = useAppSelector(s => s.workflow.isRunning);
  const { saveWorkflow } = useWorkflow();
  const { startRun, cancelRun } = useWorkflowRun();

  useEffect(() => {
    const newWF: WorkflowIR = {
      id: `wf-${Date.now()}`, name: '新建工作流', version: '1.0',
      schema: { input_schema: {}, state_variables: [] },
      nodes: [], edges: [],
    };
    dispatch(setCurrentWorkflow(newWF));
  }, [dispatch]);

  const handleSave = useCallback(async () => { await saveWorkflow(); }, [saveWorkflow]);
  const handleRun = useCallback(async () => { await startRun(); }, [startRun]);
  const handleCancel = useCallback(async () => { await cancelRun(); }, [cancelRun]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', width: '100vw' }}>
      <WorkflowToolbar onSave={handleSave} onRun={handleRun} onCancel={handleCancel} />
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden', position: 'relative' }}>
        <NodePalette />
        <WorkflowCanvas />
        <NodeConfigPanel />
        {isRunning && <RunOverlay />}
      </div>
    </div>
  );
}
