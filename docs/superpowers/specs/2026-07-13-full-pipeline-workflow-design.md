# 全流程多节点工作流 — 设计方案

> 日期: 2026-07-13
> 状态: 设计完成
> 关联: [[2026-07-09-requirements-analysis-agent-design]], [[2026-07-01-langgraph-multi-agent-refactor-design]]

## 1. 背景与动机

### 1.1 当前状态

LangGraph 5 节点流水线（analysis → design → code → review → e2e）已具备基本拓扑结构，但存在以下不足：

- **阶段衔接碎片化**：确认推进按钮在 ChatPanel 底部，与右侧文档区分离，用户视线需要在左右切换
- **文档展示不统一**：analysis 的 PRD 使用 PRDGeneratorView，design 使用 StageOutput，两套独立渲染逻辑
- **code 节点能力单薄**：单文件 Vue SFC 生成，不支持多文件工程、工具调用、实时编译反馈
- **review 节点覆盖窄**：仅检查"设计-代码匹配度"，缺乏安全/性能/可访问性等多维度审查
- **E2E 缺用户确认环节**：测试用例直接执行，用户无法审阅和修改

### 1.2 目标

将现有流水线升级为**工具增强的全流程工作台**：

1. 聊天反问完成后，点击"开始设计"按钮，进入需求分析节点，流式生成 PRD（MD → HTML），完成后右上角出现 [下一步 ▸]
2. 点击下一步 → 详细设计节点，流式生成设计文档（MD → HTML），完成后右上角 [下一步 ▸]
3. 点击下一步 → 功能开发节点，LLM 通过工具调用（Tool/Skill/MCP）迭代生成多文件工程，实时编译预览，完成后 [下一步 ▸]
4. 点击下一步 → 质量校验节点，4 个独立 Agent 并行审查安全/性能/可访问性/可维护性，输出 HTML 报告，自动修复循环
5. 点击下一步 → E2E 验证节点，先生成测试用例 MD 供用户确认，确认后分屏（上方进度 + 下方预览）自动执行

### 1.3 设计决策

| 维度 | 决策 |
|------|------|
| 反问与 PRD 生成衔接 | 聊天区完成反问 → 用户点"开始设计" → analysis node 进入 Phase 2 流式生成 PRD，跳过三层卡片 UI |
| "下一步"按钮位置 | 统一到右侧文档区右上角 StageToolbar，ChatPanel 底部移除确认按钮 |
| 流程控制 | 全部在 LangGraph 内，interrupt_before 所有节点，由"下一步"按钮恢复 |
| code 节点增强 | 工具调用 + Skill 模板 + MCP 三层体系，LLM 作为编排器迭代生成 |
| review 节点增强 | 多维度 LLM Agent 面板，并行审查 → 合并 HTML 报告 |
| E2E 分屏模式 | Phase 1：生成测试用例 MD → 用户确认；Phase 2：分屏自动执行 |

## 2. 方案选型

### 2.1 右侧面板架构选型

| 维度 | A: 统一 DocumentViewer | B: 阶段专属组件 | C: 分层架构 (选中) |
|------|------------------------|-----------------|---------------------|
| 代码复用 | 高 | 低 | 中高 |
| 灵活性 | 低（条件逻辑膨胀） | 高 | 高 |
| 新增阶段成本 | 低 | 高 | 中 |
| 与现有代码兼容 | 需大改 | 直接复用 | 渐进替换 |

选择**方案 C：分层架构 — StreamDocument + StageToolbar + 阶段容器**。

核心原则：
- `StreamDocument` 和 `StageToolbar` 高复用，analysis/design/e2e-testcases 共享
- 阶段容器只做编排，保持简洁
- 特殊 UI 的阶段（Review、E2E）有自己的容器，不污染共享组件

### 2.2 code 节点增强选型

选择**工具调用 + Skill + MCP 三层体系**，LLM 作为编排器调用工具链：

- **Tool Calls**：原子操作（create_file, write_code, compile, fix_error）
- **Skill 模板**：可复用的代码模式（crud-page, form-validation, data-dashboard 等）
- **MCP 服务**：外部上下文（component-docs, design-tokens, type-registry）

### 2.3 review 节点增强选型

选择**多维度 LLM Agent 面板**：4 个独立 Agent（安全/性能/可访问性/可维护性）并行审查，各自输出维度报告，合并为综合 HTML 报告。

## 3. 整体架构

### 3.1 节点流转

```
用户输入需求
    │
    ▼
analysis node
  ├── Phase 1: Q&A（反问阶段，聊天区交互）
  ├── Phase 2: PRD 流式生成（StreamDocument 渲染）
  └── interrupt: 等待 [下一步 ▸]
        │
        ▼
design node
  ├── 流式生成设计文档（StreamDocument 渲染）
  └── interrupt: 等待 [下一步 ▸]
        │
        ▼
code node
  ├── Phase 1: 工具调用生成多文件工程（ToolTrace + FileExplorer + PreviewFrame）
  ├── Phase 2: 编译修复循环
  └── interrupt: 等待 [下一步 ▸]
        │
        ▼
review node
  ├── 4 Agent 并行审查（MultiAgentPanel）
  ├── 合并 HTML 报告（StreamDocument）
  ├── 有问题 → 自动修复 → 重审循环
  └── interrupt: 等待 [下一步 ▸]
        │
        ▼
e2e node
  ├── Phase 1: 生成测试用例 MD（StreamDocument）
  ├── 用户审阅确认
  ├── Phase 2: 分屏自动执行（TestCaseProgress + PreviewFrame）
  └── 通过 → END / 失败 → 回退 code node
```

### 3.2 回退路径

```
review (critical) → design → code → review → e2e
review (minor/moderate) → code → review → e2e
e2e (fail) → code → review → e2e
```

复用现有 `decide_after_review` / `decide_after_e2e` 条件边 + `LoopControl` 循环控制。

## 4. 前端组件设计

### 4.1 组件树

```
GenerationView
├── ChatPanel（左 30%）
│   ├── 消息列表（Q&A 消息 + 选项按钮）
│   ├── ChatInput
│   └── "开始设计"按钮（反问完成时显示）
│
└── RightPanel（右 70%）
    ├── StepProgress（5 节点步骤条）
    ├── StageToolbar（统一，所有阶段复用）
    │   ├── 阶段标题 + 图标
    │   ├── 流式进度指示器
    │   └── [下一步 ▸]（stage_complete 后显示）
    │
    └── 阶段容器（v-if 切换）
        ├── AnalysisStagePanel  → StreamDocument + 操作栏
        ├── DesignStagePanel    → StreamDocument + 操作栏
        ├── CodeStagePanel      → TabBar + FileExplorer + PreviewFrame + ToolTracePanel
        ├── ReviewStagePanel    → MultiAgentPanel + StreamDocument(HTML 报告)
        └── E2EStagePanel       → StreamDocument(测试用例) / SplitScreen + TestCaseProgress
```

### 4.2 共享组件

#### StreamDocument

流式 MD/HTML 渲染组件，analysis/design/e2e-testcases 复用。

**Props**: `content: string`, `isStreaming: boolean`, `language: 'md' | 'html'`
**Features**: markdown-it 实时渲染、代码块语法高亮（highlight.js）、自动滚动、表格/Mermaid 支持

#### StageToolbar

统一的阶段标题栏 + "下一步"按钮。

**Props**: `title: string`, `isStreaming: boolean`, `isComplete: boolean`, `showNextButton: boolean`
**Slots**: `#extra-actions`（导出/编辑按钮）, `#status`（自定义状态指示器）
**Events**: `@next`

### 4.3 阶段专属组件

#### AnalysisStagePanel / DesignStagePanel

简洁容器：StreamDocument + StageToolbar + 导出/复制按钮。

#### CodeStagePanel

三 Tab 布局：
- **工程文件**：FileExplorer（已有，复用）
- **实时预览**：PreviewFrame（已有，复用）
- **Tool Trace**：ToolTracePanel（新增）— LLM 工具调用链可视化，点击条目可跳转到对应文件

#### ReviewStagePanel

- **MultiAgentPanel**（新增）：4 个 AgentCard 并行展示（安全/性能/可访问性/可维护性），每个显示状态图标 + 流式分析 + 发现项列表
- **StreamDocument**：合并后的 HTML 报告
- **Issue 清单**：可点击定位到对应代码行

#### E2EStagePanel

- **Phase 1**：StreamDocument 展示测试用例 MD，用户确认
- **Phase 2**：SplitScreen — 上半部分 TestCaseProgress（用例列表 + 实时执行结果），下半部分 PreviewFrame（自动操作）

## 5. 后端架构设计

### 5.1 GenerationState 扩展

```python
class GenerationState(TypedDict):
    # === 现有字段保持不变 ===
    requirement: str
    component_lib: str
    messages: list[dict]
    analysis_result: str | None
    design_result: str | None
    code_result: str | None
    review_result: str | None
    e2e_results: list[dict] | None
    review_passed: bool
    review_severity: str | None
    e2e_passed: bool
    failure_details: dict | None
    qa_rounds: int
    rollback_records: list[dict]
    rollback_count: dict[str, int]
    needs_manual_review: bool

    # === 新增字段 ===
    stage_phase: str                           # "qa" | "generating" | "complete"
    design_doc: str | None                     # 设计文档 MD
    generated_files: dict[str, str]            # 文件名 → 代码内容
    compile_errors: list[dict] | None          # 编译错误列表
    review_agent_results: list[dict] | None    # 各 Agent 审查结果
    review_report_html: str | None             # 合并后 HTML 报告
    review_issues: list[dict] | None           # 结构化 issue 列表
    e2e_test_cases_md: str | None              # 测试用例 MD 文档
    e2e_user_confirmed: bool                   # 用户已确认测试用例
```

### 5.2 code node — 工具系统

```
ai-service/app/services/generation/tools/
├── __init__.py
├── registry.py          ← ToolRegistry: 注册/查找/调用
├── file_tools.py        ← create_file, write_code, delete_file
├── compile_tool.py      ← compile_project, get_compile_errors
├── mcp_bridge.py        ← MCP 客户端: connect/search/call
└── skill_loader.py      ← Skill 模板加载: list/apply

ai-service/app/services/generation/skills/
├── crud-page.json
├── form-validation.json
├── data-dashboard.json
├── auth-guard.json
├── file-upload.json
└── responsive-layout.json

ai-service/app/services/generation/mcp/
└── servers.yaml         ← MCP 服务器配置列表
```

#### ToolRegistry

```python
@dataclass
class ToolDef:
    name: str
    description: str
    parameters: dict          # JSON Schema
    handler: Callable
    category: str             # "file" | "compile" | "mcp" | "skill"

class ToolRegistry:
    def get_schema(self) -> list[dict]: ...
    async def invoke(self, name: str, args: dict) -> ToolResult: ...
```

#### code_node — Tool-use Loop

LLM 编排器循环：
1. LLM 分析设计方案 → 规划文件结构
2. LLM 调用 `use_skill("crud-page")` → 生成模板文件
3. LLM 调用 `mcp_query("component-docs", "Table")` → 获取组件 API
4. LLM 调用 `write_code` → 逐文件填充代码
5. Tool: `compile_project` → 编译检查 → 有错误则 `fix_error` → 重新编译
6. 编译通过 → 进入 Phase 2，显示 [下一步 ▸]

最大 20 轮工具调用，每 3 轮自动触发编译检查。

### 5.3 review node — 多 Agent 并行审查

4 个 Agent 并行执行：

| Agent | 审查维度 | 关注点 |
|-------|---------|--------|
| security | 安全 | XSS、敏感数据暴露、CSRF、路由守卫 |
| performance | 性能 | 重复渲染、虚拟滚动、懒加载、打包体积 |
| accessibility | 可访问性 | ARIA 属性、键盘导航、颜色对比度、屏幕阅读器 |
| maintainability | 可维护性 | 组件大小、重复代码、硬编码、类型定义 |

每个 Agent 输出结构化 JSON issues → 合并为 HTML 报告 → 有 critical issue 则回退 code node 修复 → 重新审查。

### 5.4 e2e node — 两阶段

- **Phase 1**：LLM 生成测试用例 MD → StreamDocument 展示 → 用户确认
- **Phase 2**：前端执行自动化测试 → 分屏展示进度 → 全部通过→END，失败→code node 修复

### 5.5 graph.py — interrupt 策略

```python
app = workflow.compile(
    checkpointer=checkpointer,
    interrupt_before=["analysis", "design", "code", "review", "e2e"],
)
```

所有节点完成后暂停，由 StageToolbar [下一步 ▸] → `POST /api/v1/generation/confirm` → `Command(resume=...)` 恢复。

## 6. SSE 事件协议

### 6.1 事件总览

| 类别 | 事件 | 方向 | 前端目标 |
|------|------|------|---------|
| 通用 | `stage_start` | ← | 设置当前阶段 + Phase |
| 通用 | `stage_complete` | ← | 标记阶段完成 |
| 通用 | `human_confirm_required` | ← | StageToolbar 显示 [下一步 ▸] |
| 流式文档 | `doc_chunk` | ← | StreamDocument 追加内容 |
| 流式文档 | `{stage}_gen_start/done` | ← | 标记生成开始/完成 |
| Code | `file_start/chunk/complete` | ← | FileExplorer 逐文件更新 |
| Code | `tool_call / tool_result` | ← | ToolTracePanel 调用链 |
| Code | `code_gen_done` | ← | 编译状态汇总 |
| Review | `review_agents_start` | ← | 初始化 4 个 AgentCard |
| Review | `review_agent_chunk/done` | ← | 每个 Agent 流式输出 |
| Review | `review_report_ready` | ← | StreamDocument 渲染 HTML 报告 |
| Review | `review_fix_start/done` | ← | 自动修复状态 |
| E2E | `e2e_cases_gen_start/done` | ← | StreamDocument 测试用例 |
| E2E | `e2e_execute_start` | ← | 进入分屏执行 |
| E2E | `e2e_case_start/result` | ← | TestCaseProgress 更新 |
| E2E | `e2e_execute_done` | ← | 汇总结果 |
| 结束 | `graph_complete` | ← | 流程结束 |

### 6.2 流式文档事件（analysis/design/e2e-testcases 统一）

```
doc_chunk { content: "...", checkpoint_id: "ck_023" }
```

### 6.3 Code 阶段事件示例

```
code_gen_start     → { files: ["App.vue", "pages/Home.vue", ...] }
file_start         → { path: "App.vue", language: "vue" }
file_chunk         → { path: "App.vue", content: "<template>\n..." }
file_complete      → { path: "App.vue" }
tool_call          → { tool: "use_skill", args: {name: "crud-page"} }
tool_result        → { tool: "use_skill", ok: true }
tool_call          → { tool: "compile", args: {} }
tool_result        → { tool: "compile", ok: false, errors: [...] }
tool_call          → { tool: "fix_error", args: {file: "App.vue", line: 15} }
tool_result        → { tool: "fix_error", ok: true }
code_gen_done      → { total_files: 8, compile_errors: 0 }
```

### 6.4 Review 阶段事件示例

```
review_agents_start → { agents: [
    {key: "security", name: "安全审查", icon: "🔒"},
    {key: "performance", name: "性能分析", icon: "⚡"},
    {key: "accessibility", name: "可访问性", icon: "♿"},
    {key: "maintainability", name: "可维护性", icon: "🧩"},
]}
review_agent_chunk  → { agent: "security", issue: {...} }
review_agent_done   → { agent: "security", total_issues: 2 }
review_report_ready → { report_html: "<html>...", total_issues: 4, critical: 1 }
```

## 7. Pinia Store 扩展

### 7.1 新增 State

```typescript
// ── 阶段控制 ──
stagePhase: 'idle' | 'qa' | 'generating' | 'reviewing' | 'complete'
awaitingConfirm: boolean

// ── 流式文档（analysis/design/e2e-testcases 共享）──
docStreamingContent: string
docIsStreaming: boolean

// ── Code 阶段 ──
generatedFiles: Record<string, string>
currentGeneratingFile: string | null
toolTraces: ToolTraceEntry[]

// ── Review 阶段 ──
reviewAgents: ReviewAgentState[]
reviewReportHtml: string | null

// ── E2E 阶段 ──
e2eTestCasesMd: string | null
e2eUserConfirmed: boolean
e2eCurrentCaseId: string | null
```

### 7.2 新增类型

```typescript
interface ToolTraceEntry {
  id: string; type: 'call' | 'result'; tool: string
  args?: Record<string, any>; status: 'running' | 'done' | 'error'
  summary?: string; timestamp: number
}

interface ReviewAgentState {
  key: string; name: string; icon: string
  status: 'pending' | 'running' | 'done'
  findings: ReviewFinding[]; totalIssues: number
}

interface ReviewFinding {
  severity: 'critical' | 'high' | 'medium' | 'low'
  file: string; line: number; title: string
  description: string; fix: string
}
```

### 7.3 关键 Computed

```typescript
showStreamDocument    // analysis/design/e2e-phase1 时为 true
showNextButton        // awaitingConfirm && phase === 'complete'
reviewIssueSummary    // { total, critical, high }
compileStatus         // { hasErrors, lastCompileOk }
```

## 8. 错误处理与边界情况

### 8.1 各阶段错误矩阵

| 阶段 | 错误场景 | 处理策略 |
|------|---------|---------|
| analysis | LLM 返回格式异常 | 重试生成（最多 2 次），失败提示重新描述 |
| design | 生成中断 | 续写机制：保留已生成部分，发送续写请求 |
| code | compile 有错误 | 自动 fix_error，最多 3 轮 |
| code | 工具调用 > 20 轮 | 硬限制，取最新编译通过版本 |
| code | MCP 不可用 | 降级：LLM 凭记忆生成，ToolTrace 标注超时 |
| review | 某 Agent 超时 | 标记"未完成"，报告中注明 |
| review | 修复后问题增加 | 回退到修复前版本，标记需人工介入 |
| e2e | 页面加载超时 | 重试 3 次，仍失败→跳过标记 error |
| e2e | 全部用例失败 | 回退 code node，附带失败日志 |

### 8.2 流式中断恢复

- 每个 SSE 事件附带 `checkpoint_id`
- 前端断连后显示 [重新生成]，重连时发送 `checkpoint_id`
- 后端从 checkpoint 恢复，续传未发送内容

### 8.3 回退与循环控制

复用 `LoopControl`：
- 每节点最多回退 3 次
- 全局回退上限 10 次
- 连续无改善 2 次 → 熔断，需人工介入

### 8.4 边界情况

| 边界 | 处理 |
|------|------|
| 空需求 | ChatPanel 提示"请先描述需求" |
| 超长文档 | StreamDocument 虚拟滚动 + 目录导航 |
| 快速连点"下一步" | 按钮防抖 500ms + `isTransitioning` 锁 |
| 页面刷新 | MemorySaver checkpoint 持久化恢复 |
| 多 Tab | 后端检测重复 session → 拒绝旧请求 |
| 无预览文件 | 预览区显示"此文件无可视化预览" |
| 测试用例为空 | 跳过 E2E，标注"无测试用例" |

## 9. 实施路径

### Phase 1: 基础 — StageToolbar + 阶段流转（1-2 天）

| 步骤 | 文件 | 内容 |
|------|------|------|
| 1.1 | `stores/generation.ts` | 新增 `stagePhase`, `awaitingConfirm` |
| 1.2 | `components/StageToolbar.vue` | 新建：标题 + 进度 + 下一步按钮 |
| 1.3 | `views/GenerationView.vue` | 集成 StageToolbar |
| 1.4 | `composables/useStreamChat.ts` | 新增 `human_confirm_required` 事件 |
| 1.5 | `components/ChatPanel.vue` | 移除底部确认按钮，保留"开始设计" |

**验证**：Q&A → 开始设计 → PRD 生成 → [下一步 ▸] → 进入 design

### Phase 2: 文档流 — StreamDocument + analysis/design 统一（2-3 天）

| 步骤 | 文件 | 内容 |
|------|------|------|
| 2.1 | `components/StreamDocument.vue` | 新建：markdown-it 流式渲染 |
| 2.2 | `stores/generation.ts` | 新增 `docStreamingContent` + actions |
| 2.3 | `composables/useStreamChat.ts` | 新增 `doc_chunk` 事件 |
| 2.4 | `nodes.py` | `design_node` 流式输出设计文档 |
| 2.5 | `graph.py` | 统一为 `doc_chunk` 事件 |
| 2.6 | `components/AnalysisStagePanel.vue` | 新建 |
| 2.7 | `components/DesignStagePanel.vue` | 新建 |
| 2.8 | `components/PRDGeneratorView.vue` | 标记 deprecated |

**验证**：analysis → PRD 流式 → 下一步 → design 文档流式 → 下一步

### Phase 3: 代码生成 — 工具系统 + code node 改造（3-4 天）

| 步骤 | 文件 | 内容 |
|------|------|------|
| 3.1 | `tools/registry.py` | 新建 ToolRegistry |
| 3.2 | `tools/file_tools.py` | 新建：create_file, write_code |
| 3.3 | `tools/compile_tool.py` | 新建：compile_project |
| 3.4 | `tools/mcp_bridge.py` | 新建：MCP 客户端 |
| 3.5 | `tools/skill_loader.py` + `skills/*.json` | 新建：Skill 模板 |
| 3.6 | `nodes.py` | `code_node` 重写：Tool-use Loop |
| 3.7 | `components/ToolTracePanel.vue` | 新建 |
| 3.8 | `components/CodeStagePanel.vue` | 新建 |
| 3.9 | `composables/useStreamChat.ts` | code 事件处理 |
| 3.10 | `stores/generation.ts` | code state + actions |

**验证**：LLM 调用工具链 → 多文件生成 → 编译通过 → 预览渲染

### Phase 4: 质量审查 — 多 Agent 面板 + review node 改造（3-4 天）

| 步骤 | 文件 | 内容 |
|------|------|------|
| 4.1 | `nodes.py` | `review_node` 重写：4 Agent 并行 + HTML 报告 |
| 4.2 | `graph.py` | review→code 回退 + 重审逻辑 |
| 4.3 | `components/MultiAgentPanel.vue` | 新建 |
| 4.4 | `components/ReviewStagePanel.vue` | 新建 |
| 4.5 | `stores/generation.ts` | review state + actions |
| 4.6 | `composables/useStreamChat.ts` | review 事件处理 |

**验证**：4 Agent 并行 → 发现 3 个 issue → 自动修复 → 重审通过

### Phase 5: E2E 验证 — 分屏测试（2-3 天）

| 步骤 | 文件 | 内容 |
|------|------|------|
| 5.1 | `nodes.py` | `e2e_node` 两阶段改造 |
| 5.2 | `components/E2EStagePanel.vue` | 新建：分屏布局 |
| 5.3 | `components/TestCaseProgress.vue` | 新建 |
| 5.4 | `composables/useE2ERunner.ts` | 扩展分屏模式 |
| 5.5 | `composables/useStreamChat.ts` | e2e 事件处理 |
| 5.6 | `stores/generation.ts` | e2e state + actions |

**验证**：测试用例 MD 流式 → 用户确认 → 分屏执行 → 全部通过

### 文件改动总览

| 类型 | 后端 | 前端 |
|------|------|------|
| 新建 | `tools/` (6 文件), `skills/` (5 文件), `mcp/servers.yaml` | `StageToolbar`, `StreamDocument`, 5 个阶段面板, `ToolTracePanel`, `MultiAgentPanel`, `TestCaseProgress` |
| 重写 | `nodes.py` (3 节点), `graph.py` (interrupt) | `GenerationView.vue` (右侧面板) |
| 扩展 | `state.py`, `harness.py`, `servicer.py` | `generation.ts`, `useStreamChat.ts`, `useE2ERunner.ts` |
| 废弃 | — | `PRDGeneratorView.vue`, ChatPanel 底部确认按钮 |

**总工期**：11-16 天（可并行缩减至 8-12 天）

## 10. 安全考量

- **Prompt 注入防护**：用户输入拼入 prompt 前转义，工具调用参数校验
- **XSS 防护**：StreamDocument 渲染 MD → HTML 前做 sanitize（DOMPurify）
- **MCP 安全**：MCP bridge 仅连接白名单服务器，命令注入过滤
- **代码执行隔离**：生成的代码在 iframe sandbox 内编译和预览
- **速率限制**：每 session 最多 50 次工具调用，全局回退上限 10 次
