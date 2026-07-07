# AI 工作流编排器 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 ai-workflow 微应用中实现可视化 AI Agent 工作流编排器，前端 React Flow 画布 + 后端 LangGraph 动态编译执行

**Architecture:** 前端画布产出 Workflow IR JSON → 后端 WorkflowCompiler 编译为 LangGraph StateGraph → DynamicGraphRunner 异步执行并通过 SSE 推送节点状态 → 前端 RunOverlay 实时渲染执行进度。四节点类型：LLM、Router、HumanConfirm、Code，通过 NodeRegistry 注册机制扩展。

**Tech Stack:** Python (LangGraph, asyncio, subprocess 沙箱), React 18 (React Flow, Redux Toolkit, Tailwind CSS, TypeScript)

---

## Phase 1: 后端核心 — Workflow IR 编译 + 执行链路

### Task 1.1: Define Workflow IR types

**Files:**
- Create: `ai-design-platform-server/ai-service/app/services/workflow/__init__.py`
- Create: `ai-design-platform-server/ai-service/app/services/workflow/ir_types.py`
- Create: `ai-design-platform-server/ai-service/tests/test_ir_types.py`

**Steps:**

- [ ] Create package `__init__.py` with docstring
- [ ] Write test_ir_types.py with tests for NodeDef parsing, config dataclasses (LLM/Router/HumanConfirm/Code), WorkflowIR roundtrip JSON serialization, template resolution `{state.xxx}`
- [ ] Run tests (expect FAIL)
- [ ] Implement ir_types.py with dataclasses: `WorkflowIR`, `NodeDef`, `EdgeDef`, `WorkflowSchema`, `LLMNodeConfig`, `RouterNodeConfig` (+ `RouterBranch`), `HumanConfirmNodeConfig` (+ `HumanConfirmField`), `CodeNodeConfig`, plus `resolve_template()` function using regex `\{state\.([\w.]+)\}`
- [ ] Run tests (expect PASS)

### Task 1.2: NodeHandler base + Registry

**Files:**
- Create: `ai-design-platform-server/ai-service/app/services/workflow/handlers/__init__.py`
- Create: `ai-design-platform-server/ai-service/app/services/workflow/registry.py`
- Create: `ai-design-platform-server/ai-service/tests/test_registry.py`

**Steps:**

- [ ] Define `NodeHandler` ABC in handlers/__init__.py with `node_type: str`, abstract `async execute(state, config) -> dict`, abstract `compile_to_langgraph(node_def) -> Callable`
- [ ] Implement `NodeRegistry` class with `register(handler)`, `lookup(node_type) -> NodeHandler`, `list_types()`, `reset()` methods
- [ ] Write registry tests (register, lookup, unknown type raises, list_types)
- [ ] Run tests: PASS

### Task 1.3: LLM Handler

**Files:**
- Create: `ai-design-platform-server/ai-service/app/services/workflow/handlers/llm_handler.py`
- Create: `ai-design-platform-server/ai-service/tests/test_handlers.py`

**Steps:**

- [ ] Implement `LLMHandler(NodeHandler)` with `node_type = "llm"`
- [ ] `execute()`: resolves `{state.xxx}` templates in system_prompt and user_prompt via `resolve_template()`, calls `_llm_generate()` (reused from generation/nodes.py), returns `{output_key: result_text}`
- [ ] `compile_to_langgraph()`: returns async fn that calls `self.execute(state, config)`
- [ ] Write tests with mocked `_llm_generate`, verify template resolution and output_key
- [ ] Run tests: PASS

### Task 1.4: Code Handler + Sandbox

**Files:**
- Create: `ai-design-platform-server/ai-service/app/services/workflow/sandbox.py`
- Create: `ai-design-platform-server/ai-service/app/services/workflow/handlers/code_handler.py`
- Create: `ai-design-platform-server/ai-service/tests/test_sandbox.py`

**Steps:**

- [ ] Implement `SandboxExecutor` with `execute(language, code, state, timeout) -> dict` using subprocess isolation
- [ ] Script template: serialize state via `sys.argv`, exec user code with `{"state": state, "json": json}` namespace, capture `result` variable or all locals as JSON stdout
- [ ] Timeout via `subprocess.run(timeout=...)`, error handling with structured JSON stderr
- [ ] Implement `CodeHandler(NodeHandler)` with `node_type = "code"`, resolves templates in code, calls SandboxExecutor, returns `{output_key: result}`
- [ ] Write tests: basic execution, timeout, syntax error, blocked imports
- [ ] Run tests: PASS

### Task 1.5: Router Handler

**Files:**
- Create: `ai-design-platform-server/ai-service/app/services/workflow/handlers/router_handler.py`

**Steps:**

- [ ] Implement `RouterHandler(NodeHandler)` with `node_type = "router"`
- [ ] `execute()` returns `{}` (pass-through)
- [ ] `compile_to_langgraph()` returns `None` (handled specially by compiler)
- [ ] Static method `build_router_function(branches) -> Callable`: compiles branch conditions with `compile(condition, "<router>", "eval")`, returns fn that evaluates conditions against `{"state": state}` safe namespace, returns matching label or default
- [ ] Router tested via compiler integration (Task 1.7)

### Task 1.6: Human Confirm Handler

**Files:**
- Create: `ai-design-platform-server/ai-service/app/services/workflow/handlers/human_handler.py`

**Steps:**

- [ ] Implement `HumanConfirmHandler(NodeHandler)` with `node_type = "human_confirm"`
- [ ] `execute()` reads `state["_human_response"]`, maps response fields to state keys per config.fields, returns updates
- [ ] `compile_to_langgraph()` returns async fn wrapping execute
- [ ] Handler tested via compiler integration (Task 1.7)

### Task 1.7: WorkflowCompiler

**Files:**
- Create: `ai-design-platform-server/ai-service/app/services/workflow/compiler.py`
- Create: `ai-design-platform-server/ai-service/tests/test_compiler.py`

**Steps:**

- [ ] Implement `WorkflowCompiler.compile(ir: WorkflowIR) -> CompiledStateGraph`:
  - Step 1: Build dynamic TypedDict from state_variables
  - Step 2: Create `StateGraph(DynamicState)`
  - Step 3: For each node, `registry.lookup(type).compile_to_langgraph()` → `add_node(id, fn)`
  - Step 4: Set entry point to first node
  - Step 5: Add edges: regular edges → `add_edge`, router edges → `add_conditional_edges` with `RouterHandler.build_router_function()`
  - Step 6: Collect human_confirm node ids → `compile(checkpointer=MemorySaver(), interrupt_before=[...])`
- [ ] Write tests: 2-node linear compile, router conditional compile, human_confirm interrupt collection, empty workflow raises
- [ ] Run tests: PASS

### Task 1.8: DynamicGraphRunner

**Files:**
- Create: `ai-design-platform-server/ai-service/app/services/workflow/runner.py`

**Steps:**

- [ ] Implement `DynamicGraphRunner`:
  - `run(ir, initial_state, thread_id) -> AsyncIterator[dict]`: compiles IR, runs `app.astream()`, yields SSE event dicts (`workflow_start`, `stage_start`, `stage_complete`, `human_confirm_required`, `node_error`, `workflow_complete`)
  - `resume(thread_id, human_response, ir) -> AsyncIterator[dict]`: calls `app.update_state(config, {"_human_response": response})` then continues streaming
  - Helper `_summarize(node_id, node_type, output)`: extracts output preview per node type
- [ ] Write integration test (Task 3.5 tests this end-to-end)

### Task 1.9: WorkflowServicer

**Files:**
- Create: `ai-design-platform-server/ai-service/app/services/workflow/servicer.py`

**Steps:**

- [ ] Implement `WorkflowServicer` with in-memory workflow store:
  - `save(ir_dict) -> dict`: persist WorkflowIR
  - `list_workflows() -> list[dict]`: list summaries
  - `get(workflow_id) -> dict | None`: get full IR
  - `delete(workflow_id) -> bool`
  - `run(workflow_id, inputs) -> AsyncIterator[dict]`: load IR, build initial_state, create DynamicGraphRunner, yield events
  - `resume(workflow_id, human_response) -> AsyncIterator[dict]`: resume paused workflow
  - `cancel(workflow_id) -> bool`
- [ ] Auto-register all 4 handlers on import

---

## Phase 2: 前端画布 — React Flow 编辑器

### Task 2.1: Install dependencies + Define TypeScript types

**Files:**
- Modify: `ai-design-platform-web/packages/ai-workflow/package.json`
- Create: `ai-design-platform-web/packages/ai-workflow/src/types/workflow.ts`

**Steps:**

- [ ] Run `pnpm add @xyflow/react --filter @ai-design/ai-workflow`
- [ ] Define TypeScript interfaces matching backend IR: `WorkflowIR`, `NodeDef`, `EdgeDef`, `WorkflowSchema`, `LLMNodeConfig`, `RouterNodeConfig`, `RouterBranch`, `HumanConfirmNodeConfig`, `HumanConfirmField`, `CodeNodeConfig`
- [ ] Define React Flow types: `WorkflowNodeData` (label, nodeType, config, status, summary), `WorkflowEdgeData` (condition), `WorkflowNodeStatus` ('pending'|'running'|'done'|'error')
- [ ] Define SSE event type: `WorkflowEvent` {event_type, stage, data}
- [ ] Verify with `npx tsc --noEmit`

### Task 2.2: Extend Redux workflowSlice

**Files:**
- Modify: `ai-design-platform-web/packages/ai-workflow/src/store/slices/workflowSlice.ts`

**Steps:**

- [ ] Rewrite workflowSlice with full state: `currentWorkflow: WorkflowIR | null`, `isDirty`, `selectedNodeId`, `nodeStatuses: Record<string, WorkflowNodeStatus>`, `isRunning`, `runLogs: string[]`
- [ ] Add reducers: `setCurrentWorkflow`, `addNode`, `updateNode`, `removeNode`, `addEdge`, `removeEdge`, `setSelectedNode`, `setNodeStatus`, `resetNodeStatuses`, `setIsRunning`, `appendRunLog`, `markClean`
- [ ] Verify types compile

### Task 2.3: BaseNode component

**Files:**
- Create: `ai-design-platform-web/packages/ai-workflow/src/components/nodes/BaseNode.tsx`

**Steps:**

- [ ] Implement `BaseNode` React component rendering:
  - Status indicator dot (color-coded: pending=gray, running=blue+pulse, done=green, error=red)
  - Type icon (llm=🧠, router=🔀, human_confirm=✋, code=⚡)
  - Node label + type subtitle
  - Optional summary text (shown after stage_complete)
  - Top Handle (target) + Bottom Handle (source)
  - Selected border highlight + running/error glow

### Task 2.4: Specific node + edge components

**Files:**
- Create: `ai-design-platform-web/packages/ai-workflow/src/components/nodes/LLMNode.tsx`
- Create: `ai-design-platform-web/packages/ai-workflow/src/components/nodes/RouterNode.tsx`
- Create: `ai-design-platform-web/packages/ai-workflow/src/components/nodes/HumanNode.tsx`
- Create: `ai-design-platform-web/packages/ai-workflow/src/components/nodes/CodeNode.tsx`
- Create: `ai-design-platform-web/packages/ai-workflow/src/components/edges/WorkflowEdge.tsx`

**Steps:**

- [ ] LLMNode, HumanNode, CodeNode: thin wrappers around BaseNode
- [ ] RouterNode: extends BaseNode with multiple labeled source handles (one per branch), positioned horizontally
- [ ] WorkflowEdge: custom edge rendering condition label in amber badge using EdgeLabelRenderer at midpoint of Bezier path

### Task 2.5: WorkflowCanvas

**Files:**
- Create: `ai-design-platform-web/packages/ai-workflow/src/components/WorkflowCanvas.tsx`

**Steps:**

- [ ] Implement React Flow canvas wrapper:
  - Convert WorkflowIR nodes/edges → React Flow nodes/edges with useMemo
  - Sync node statuses from Redux → React Flow data
  - Handle onConnect → dispatch addEdge + update edges state
  - Handle onNodeClick → dispatch setSelectedNode
  - Handle onNodeDragStop → dispatch updateNode position
  - Enable drag-and-drop via onDragOver/onDrop from useNodeDrag hook
  - Disable edits when isRunning
  - Render Background (dots), Controls, MiniMap (color-coded by node type)
  - Register nodeTypes and edgeTypes

### Task 2.6: NodePalette + useNodeDrag

**Files:**
- Create: `ai-design-platform-web/packages/ai-workflow/src/composables/useNodeDrag.ts`
- Create: `ai-design-platform-web/packages/ai-workflow/src/components/panels/NodePalette.tsx`

**Steps:**

- [ ] Implement `useNodeDrag()` hook: onDragOver prevents default, onDrop reads `application/workflow-node-type` from dataTransfer, creates NodeDef with auto-id, default config per type, dispatches addNode
- [ ] Define `NODE_TYPE_TEMPLATES` with default configs for each type
- [ ] Implement `NodePalette`: renders 4 draggable node-type cards (icon + label), onDragStart sets dataTransfer data
- [ ] Show "我的工作流" section listing saved workflows from Redux

### Task 2.7: NodeConfigPanel + WorkflowToolbar

**Files:**
- Create: `ai-design-platform-web/packages/ai-workflow/src/components/panels/NodeConfigPanel.tsx`
- Create: `ai-design-platform-web/packages/ai-workflow/src/components/WorkflowToolbar.tsx`

**Steps:**

- [ ] Implement `NodeConfigPanel`:
  - Shows empty state when no node selected
  - Common: label input (editable when not running)
  - LLM-specific: model, output_key, system_prompt textarea, user_prompt textarea with `{state.xxx}` hint
  - Code-specific: language, output_key, code textarea (10 rows), timeout number input
  - Human_confirm-specific: message, timeout
  - Router: informational text about configuring conditions on edges
  - Shows node ID at bottom
- [ ] Implement `WorkflowToolbar`:
  - Shows workflow name + dirty indicator
  - Save button (disabled if not dirty), Run button (disabled if no nodes), Cancel button (red, pulse animation when running)

### Task 2.8: WorkflowView page

**Files:**
- Create: `ai-design-platform-web/packages/ai-workflow/src/pages/WorkflowView.tsx`

**Steps:**

- [ ] Implement `WorkflowView`: 3-column flex layout (NodePalette | WorkflowCanvas | NodeConfigPanel) + WorkflowToolbar on top
- [ ] Initialize empty workflow on mount if none loaded
- [ ] Wire up onSave → useWorkflow.saveWorkflow(), onRun → useWorkflowRun.startRun(), onCancel → useWorkflowRun.cancelRun()
- [ ] Show RunOverlay when isRunning

### Task 2.9: Update routes

**Files:**
- Modify: `ai-design-platform-web/packages/ai-workflow/src/router/index.tsx`
- Modify: `ai-design-platform-web/packages/ai-workflow/src/App.tsx`

**Steps:**

- [ ] Update routes to use WorkflowView as the index route
- [ ] Clean up App.tsx (remove old nav links, keep minimal layout)

---

## Phase 3: 前后端联通 — 运行监控 + Human-in-the-loop

### Task 3.1: useWorkflow hook

**Files:**
- Create: `ai-design-platform-web/packages/ai-workflow/src/composables/useWorkflow.ts`

**Steps:**

- [ ] Implement `useWorkflow()` hook:
  - `saveWorkflow()`: POST `/api/v1/workflow/save` with currentWorkflow JSON, update id if server assigned one, dispatch markClean
  - `listWorkflows()`: GET `/api/v1/workflow/list`, dispatch setWorkflows
  - `loadWorkflow(id)`: GET `/api/v1/workflow/{id}`, dispatch setCurrentWorkflow

### Task 3.2: useWorkflowRun hook

**Files:**
- Create: `ai-design-platform-web/packages/ai-workflow/src/composables/useWorkflowRun.ts`

**Steps:**

- [ ] Implement `useWorkflowRun()` hook:
  - `startRun()`: save workflow first, then open EventSource to SSE endpoint, parse events, dispatch setNodeStatus/appendRunLog per event type
  - Handle `human_confirm_required` → setHumanConfirm state for dialog display
  - `submitHumanConfirm(response)`: POST `/api/v1/workflow/{id}/resume` with response JSON
  - `cancelRun()`: close EventSource, reset statuses
  - Handle SSE error → close and setIsRunning(false)

### Task 3.3: RunOverlay component

**Files:**
- Create: `ai-design-platform-web/packages/ai-workflow/src/components/panels/RunOverlay.tsx`

**Steps:**

- [ ] Implement `RunOverlay`:
  - Bottom-left log panel: dark terminal-style, auto-scrolling, shows runLogs from Redux
  - Human confirm dialog: modal overlay with message + dynamic form fields (boolean=radio, text=input), confirm button triggers submitHumanConfirm
  - Both positioned absolutely over canvas

### Task 3.4: Backend REST endpoints wiring

**Files:**
- Modify: `ai-design-platform-server/ai-service/app/main.py`

**Steps:**

- [ ] Add FastAPI/HTTP routes for workflow CRUD + execution (if not using gRPC gateway):
  - `POST /api/v1/workflow/save` → WorkflowServicer.save()
  - `GET /api/v1/workflow/list` → WorkflowServicer.list_workflows()
  - `GET /api/v1/workflow/{id}` → WorkflowServicer.get()
  - `GET /api/v1/workflow/{id}/run` → SSE streaming via WorkflowServicer.run()
  - `POST /api/v1/workflow/{id}/resume` → SSE streaming via WorkflowServicer.resume()
  - `POST /api/v1/workflow/{id}/cancel` → WorkflowServicer.cancel()

### Task 3.5: Integration test

**Files:**
- Create: `ai-design-platform-server/ai-service/tests/test_workflow_integration.py`

**Steps:**

- [ ] Write end-to-end test: 2-node LLM pipeline, mock _llm_generate, compile → run → verify event sequence (workflow_start, 2x stage_start/complete, workflow_complete), verify LLM called twice
- [ ] Run test: PASS

---

## File Change Summary

### Backend (ai-service)

| Action | File |
|--------|------|
| Create | `app/services/workflow/__init__.py` |
| Create | `app/services/workflow/ir_types.py` |
| Create | `app/services/workflow/registry.py` |
| Create | `app/services/workflow/compiler.py` |
| Create | `app/services/workflow/runner.py` |
| Create | `app/services/workflow/sandbox.py` |
| Create | `app/services/workflow/servicer.py` |
| Create | `app/services/workflow/handlers/__init__.py` |
| Create | `app/services/workflow/handlers/llm_handler.py` |
| Create | `app/services/workflow/handlers/router_handler.py` |
| Create | `app/services/workflow/handlers/human_handler.py` |
| Create | `app/services/workflow/handlers/code_handler.py` |
| Create | `tests/test_ir_types.py` |
| Create | `tests/test_registry.py` |
| Create | `tests/test_handlers.py` |
| Create | `tests/test_sandbox.py` |
| Create | `tests/test_compiler.py` |
| Create | `tests/test_workflow_integration.py` |
| Modify | `app/main.py` (add HTTP routes) |

### Frontend (ai-workflow)

| Action | File |
|--------|------|
| Create | `src/types/workflow.ts` |
| Create | `src/pages/WorkflowView.tsx` |
| Create | `src/components/WorkflowCanvas.tsx` |
| Create | `src/components/WorkflowToolbar.tsx` |
| Create | `src/components/nodes/BaseNode.tsx` |
| Create | `src/components/nodes/LLMNode.tsx` |
| Create | `src/components/nodes/RouterNode.tsx` |
| Create | `src/components/nodes/HumanNode.tsx` |
| Create | `src/components/nodes/CodeNode.tsx` |
| Create | `src/components/edges/WorkflowEdge.tsx` |
| Create | `src/components/panels/NodePalette.tsx` |
| Create | `src/components/panels/NodeConfigPanel.tsx` |
| Create | `src/components/panels/RunOverlay.tsx` |
| Create | `src/composables/useWorkflow.ts` |
| Create | `src/composables/useWorkflowRun.ts` |
| Create | `src/composables/useNodeDrag.ts` |
| Modify | `src/store/slices/workflowSlice.ts` |
| Modify | `src/router/index.tsx` |
| Modify | `src/App.tsx` |
| Modify | `package.json` (add @xyflow/react) |
