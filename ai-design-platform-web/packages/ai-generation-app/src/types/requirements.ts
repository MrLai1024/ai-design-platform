// src/types/requirements.ts — 需求分析结构化类型

export type AnalysisMode = 'new' | 'edit' | 'append' | 'continue'

export interface TargetUser {
  role: string
  description: string
}

export interface FeatureModule {
  id: string
  name: string
  description: string
  priority: 'must' | 'should' | 'nice'
  completeness: number
  confirmed: boolean
}

export interface PageNode {
  id: string
  name: string
  parent_id: string | null
  page_type: 'list' | 'detail' | 'form' | 'dashboard' | 'custom'
  features: string[]
}

export interface FieldDef {
  name: string
  type: 'text' | 'number' | 'date' | 'dropdown' | 'tag' | 'boolean' | 'custom'
  required: boolean
}

export interface ActionDef {
  label: string
  type: 'edit' | 'create' | 'delete' | 'export' | 'custom'
}

export interface PageDetail {
  display_fields: FieldDef[]
  action_buttons: ActionDef[]
  related_data: string[]
  layout_notes: string
}

export interface TechConstraints {
  framework: string
  component_lib: string
  data_source: string
  special_requirements: string[]
}

export interface DataEntity {
  name: string
  fields: Array<{ name: string; type: string; required: boolean }>
}

export interface VisionData {
  project_name: string
  target_users: TargetUser[]
  core_problem: string
  success_criteria: string[]
  scope_note: string
}

export interface RequirementsState {
  session_id: string
  mode: AnalysisMode
  version: number
  parent_version: number | null
  layer: number
  layer_status: Record<string, 'pending' | 'active' | 'done'>
  history: StateSnapshot[]
  vision: VisionData
  features: FeatureModule[]
  pages: PageNode[]
  page_details: Record<string, PageDetail>
  tech_constraints: TechConstraints
  data_entities: DataEntity[]
}

export interface StateSnapshot {
  timestamp: number
  layer: number
  reason: string
  state_json: string
}

export interface RequirementQuestion {
  text: string
  options?: string[]
  skippable: boolean
}

export interface LayerProgress {
  layer: number
  total_layers: number
  done_count: number
  pending_count: number
}

export type AnalysisPanelMode = 'card' | 'prd'
