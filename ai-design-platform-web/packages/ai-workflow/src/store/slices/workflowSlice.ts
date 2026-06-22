import { createSlice, type PayloadAction } from '@reduxjs/toolkit';

export interface Workflow {
  id: string;
  name: string;
  status: 'draft' | 'running' | 'completed' | 'failed';
}

export interface WorkflowState {
  loading: boolean;
  workflows: Workflow[];
}

export const initialState: WorkflowState = {
  loading: false,
  workflows: [],
};

const workflowSlice = createSlice({
  name: 'workflow',
  initialState,
  reducers: {
    setLoading(state, action: PayloadAction<boolean>) {
      state.loading = action.payload;
    },
    setWorkflows(state, action: PayloadAction<Workflow[]>) {
      state.workflows = action.payload;
    },
    addWorkflow(state, action: PayloadAction<Workflow>) {
      state.workflows.push(action.payload);
    },
  },
});

export const { setLoading, setWorkflows, addWorkflow } = workflowSlice.actions;
export default workflowSlice.reducer;
