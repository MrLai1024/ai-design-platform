import { useCallback } from 'react';
import { useAppSelector, useAppDispatch } from '../store';
import { setWorkflows, setCurrentWorkflow, markClean, setLoading } from '../store/slices/workflowSlice';
import type { WorkflowIR } from '../types/workflow';

const API_BASE = '/api/v1/workflow';

export function useWorkflow() {
  const dispatch = useAppDispatch();
  const currentWorkflow = useAppSelector(s => s.workflow.currentWorkflow);

  const saveWorkflow = useCallback(async () => {
    if (!currentWorkflow) return;
    dispatch(setLoading(true));
    try {
      const res = await fetch(`${API_BASE}/save`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(currentWorkflow),
      });
      const data = await res.json();
      if (data.id && data.id !== currentWorkflow.id) {
        dispatch(setCurrentWorkflow({ ...currentWorkflow, id: data.id }));
      }
      dispatch(markClean());
    } catch (err) {
      console.error('Failed to save workflow:', err);
    } finally {
      dispatch(setLoading(false));
    }
  }, [currentWorkflow, dispatch]);

  const listWorkflows = useCallback(async () => {
    dispatch(setLoading(true));
    try {
      const res = await fetch(`${API_BASE}/list`);
      const data = await res.json();
      dispatch(setWorkflows(data.workflows || []));
    } catch (err) {
      console.error('Failed to list workflows:', err);
    } finally {
      dispatch(setLoading(false));
    }
  }, [dispatch]);

  const loadWorkflow = useCallback(async (id: string) => {
    dispatch(setLoading(true));
    try {
      const res = await fetch(`${API_BASE}/${id}`);
      const data = await res.json();
      if (data) dispatch(setCurrentWorkflow(data as WorkflowIR));
    } catch (err) {
      console.error('Failed to load workflow:', err);
    } finally {
      dispatch(setLoading(false));
    }
  }, [dispatch]);

  return { saveWorkflow, listWorkflows, loadWorkflow };
}
