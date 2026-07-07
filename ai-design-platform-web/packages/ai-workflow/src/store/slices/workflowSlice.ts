import { createSlice, type PayloadAction } from '@reduxjs/toolkit';
import type { WorkflowIR, NodeDef, EdgeDef, WorkflowNodeStatus } from '../../types/workflow';

interface WorkflowListItem {
  id: string;
  name: string;
  version: string;
}

interface WorkflowState {
  loading: boolean;
  workflows: WorkflowListItem[];
  currentWorkflow: WorkflowIR | null;
  isDirty: boolean;
  selectedNodeId: string | null;
  nodeStatuses: Record<string, WorkflowNodeStatus>;
  isRunning: boolean;
  runLogs: string[];
}

const initialState: WorkflowState = {
  loading: false,
  workflows: [],
  currentWorkflow: null,
  isDirty: false,
  selectedNodeId: null,
  nodeStatuses: {},
  isRunning: false,
  runLogs: [],
};

const workflowSlice = createSlice({
  name: 'workflow',
  initialState,
  reducers: {
    setLoading(state, action: PayloadAction<boolean>) { state.loading = action.payload; },
    setWorkflows(state, action: PayloadAction<WorkflowListItem[]>) { state.workflows = action.payload; },
    setCurrentWorkflow(state, action: PayloadAction<WorkflowIR | null>) {
      state.currentWorkflow = action.payload;
      state.isDirty = false;
      state.selectedNodeId = null;
      state.nodeStatuses = {};
    },
    addNode(state, action: PayloadAction<NodeDef>) {
      if (state.currentWorkflow) {
        state.currentWorkflow.nodes.push(action.payload);
        state.isDirty = true;
      }
    },
    updateNode(state, action: PayloadAction<{ id: string; changes: Partial<NodeDef> }>) {
      if (state.currentWorkflow) {
        const idx = state.currentWorkflow.nodes.findIndex(n => n.id === action.payload.id);
        if (idx !== -1) {
          Object.assign(state.currentWorkflow.nodes[idx], action.payload.changes);
          state.isDirty = true;
        }
      }
    },
    removeNode(state, action: PayloadAction<string>) {
      if (state.currentWorkflow) {
        state.currentWorkflow.nodes = state.currentWorkflow.nodes.filter(n => n.id !== action.payload);
        state.currentWorkflow.edges = state.currentWorkflow.edges.filter(
          e => e.source !== action.payload && e.target !== action.payload
        );
        state.isDirty = true;
        if (state.selectedNodeId === action.payload) state.selectedNodeId = null;
      }
    },
    addEdge(state, action: PayloadAction<EdgeDef>) {
      if (state.currentWorkflow) {
        state.currentWorkflow.edges.push(action.payload);
        state.isDirty = true;
      }
    },
    removeEdge(state, action: PayloadAction<string>) {
      if (state.currentWorkflow) {
        state.currentWorkflow.edges = state.currentWorkflow.edges.filter(e => e.id !== action.payload);
        state.isDirty = true;
      }
    },
    setSelectedNode(state, action: PayloadAction<string | null>) { state.selectedNodeId = action.payload; },
    setNodeStatus(state, action: PayloadAction<{ nodeId: string; status: WorkflowNodeStatus }>) {
      state.nodeStatuses[action.payload.nodeId] = action.payload.status;
    },
    resetNodeStatuses(state) { state.nodeStatuses = {}; },
    setIsRunning(state, action: PayloadAction<boolean>) {
      state.isRunning = action.payload;
      if (!action.payload) state.runLogs = [];
    },
    appendRunLog(state, action: PayloadAction<string>) { state.runLogs.push(action.payload); },
    markClean(state) { state.isDirty = false; },
  },
});

export const {
  setLoading, setWorkflows, setCurrentWorkflow, addNode, updateNode, removeNode,
  addEdge, removeEdge, setSelectedNode, setNodeStatus, resetNodeStatuses,
  setIsRunning, appendRunLog, markClean,
} = workflowSlice.actions;
export default workflowSlice.reducer;
