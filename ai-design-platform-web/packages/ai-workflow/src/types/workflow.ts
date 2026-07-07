export interface LLMNodeConfig {
  model: string;
  system_prompt: string;
  user_prompt: string;
  temperature?: number;
  max_tokens?: number;
  output_key: string;
}

export interface RouterBranch {
  label: string;
  condition: string;
}

export interface RouterNodeConfig {
  branches: RouterBranch[];
}

export interface HumanConfirmField {
  key: string;
  label: string;
  type: 'boolean' | 'text' | 'select';
  required?: boolean;
}

export interface HumanConfirmNodeConfig {
  message: string;
  fields: HumanConfirmField[];
  timeout?: number;
}

export interface CodeNodeConfig {
  language: 'python' | 'javascript';
  code: string;
  timeout?: number;
  output_key: string;
}

export type WorkflowNodeConfig =
  | LLMNodeConfig
  | RouterNodeConfig
  | HumanConfirmNodeConfig
  | CodeNodeConfig;

export interface WorkflowSchema {
  input_schema: Record<string, unknown>;
  output_schema?: Record<string, unknown>;
  state_variables: string[];
}

export interface NodeDef {
  id: string;
  type: string;
  label: string;
  position: { x: number; y: number };
  config: Record<string, unknown>;
}

export interface EdgeDef {
  id: string;
  source: string;
  target: string;
  condition?: string;
}

export interface WorkflowIR {
  id: string;
  name: string;
  version: string;
  description?: string;
  schema: WorkflowSchema;
  nodes: NodeDef[];
  edges: EdgeDef[];
}

// React Flow types
export type WorkflowNodeStatus = 'pending' | 'running' | 'done' | 'error';

export interface WorkflowNodeData {
  [key: string]: unknown;
  label: string;
  nodeType: string;
  config: Record<string, unknown>;
  status: WorkflowNodeStatus;
  summary?: string;
}

export interface WorkflowEdgeData {
  [key: string]: unknown;
  condition?: string;
}

export interface WorkflowEvent {
  event_type: string;
  stage: string;
  data: Record<string, unknown>;
}
