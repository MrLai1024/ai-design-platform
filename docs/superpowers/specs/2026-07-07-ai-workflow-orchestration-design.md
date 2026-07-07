# AI 工作流编排器设计方案

> 日期: 2026-07-07
> 状态: 设计中
> 关联: [[2026-07-01-langgraph-multi-agent-refactor-design]]

## 1. 背景与动机

### 1.1 当前状态

`ai-workflow` 微应用目前是一个空的 React 脚手架，只有基础路由和一个占位的 Redux store（`workflowSlice.ts` 定义了 `Workflow` 和 `WorkflowState` 类型，但只有 loading/workflows CRUD）。

后端已有基于 LangGraph 的 5 节点硬编码流水线（analysis → design → code → review → e2e），用于 AI 代码生成场景。该流水线固定在 [graph.py](../ai-design-platform-server/ai-service/app/services/generation/graph.py) 中，拓扑不可变。

### 1.2 目标

在 `ai-workflow` 微应用中实现**可视化 AI Agent 工作流编排器**：

1. 用户通过拖拽节点和连线，在画布上自由设计 Agent 工作流拓扑（类似 Dify/Coze/n8n）
2. Backend 将用户设计的工作流编译为 LangGraph StateGraph 并执行
3. 运行时通过 SSE 实时推送节点状态到前端画布
4. 支持 Human-in-the-loop（人工确认节点暂停等待用户输入）
5. 复用现有 AgentHarness、LoopControl、EvalHarness 基础设施

### 1.3 MVP 范围

- **节点类型**: LLM 调用、条件路由、人工确认、代码执行（4 种）
- **执行引擎**: LangGraph 为主 + 自定义扩展（NodeHandler 注册机制）
- **前端**: React Flow 画布 + 三栏布局（工具箱/画布/配置面板）
- **策略**: 前后端并行推进，最小闭环优先

## 2. 方案选型

选择**方案 B：抽象工作流模型 + LangGraph 适配器**。

定义平台无关的 Workflow IR（中间表示），前端画布产生 Workflow JSON → 后端 `WorkflowCompiler` 编译为 LangGraph StateGraph 执行。前端和后端通过 IR 解耦，双方独立演进。

### 方案对比

| 维度 | A: 深度 LangGraph 集成 | B: 抽象 IR + 适配器 (选中) | C: JSON 配置 + 模板 |
|------|----------------------|--------------------------|-------------------|
| 前端解耦程度 | 低（受 LangGraph 概念约束） | 高（IR 是纯 JSON） | 高 |
| 扩展性 | 中（新节点需懂 LangGraph） | 高（注册 Handler 即可） | 低（固定模板） |
| 初期工作量 | 中 | 中高 | 低 |
| 复用现有基础设施 | 直接 | 适配层桥接 | 直接 |
| 可视化能力 | 强 | 强 | 弱（不是可视化设计器） |

## 3. 核心数据模型: Workflow IR

Workflow IR 是前后端之间的契约——前端画布产出这份 JSON，后端编译器消费它。

### 3.1 IR 结构

```
Workflow IR = Metadata + Schema + Nodes[] + Edges[]
```

| 层次 | 字段 | 说明 |
|------|------|------|
| Metadata | id, name, description, version, created_at | 工作流元信息 |
| Schema | input_schema, output_schema, state_variables[] | 工作流入参/出参/共享状态的 JSON Schema |
| Nodes[] | id, type, label, position(x,y), config | 每个节点的 type 决定 config schema |
| Edges[] | id, source, target, condition? | source→target 连线，可选 condition 做条件路由 |

### 3.2 MVP 节点类型定义

#### LLM 节点 (`type: "llm"`)

```json
{
  "id": "n1",
  "type": "llm",
  "label": "需求分析",
  "position": {"x": 100, "y": 50},
  "config": {
    "model": "glm-5.2",
    "system_prompt": "你是一个资深产品需求分析师...",
    "user_prompt": "分析以下需求: {state.requirement}",
    "temperature": 0.7,
    "max_tokens": 4096,
    "output_key": "analysis_result"
  }
}
```

- `user_prompt` 支持 `{state.xxx}` 模板语法引用上游节点产出
- `output_key` 指定输出写入 state 的 key

#### 条件路由节点 (`type: "router"`)

```json
{
  "id": "n4",
  "type": "router",
  "label": "判断结果",
  "position": {"x": 100, "y": 350},
  "config": {
    "branches": [
      {"label": "通过", "condition": "state.review_passed == true"},
      {"label": "需修改", "condition": "default"}
    ]
  }
}
```

- 每条分支有 `label`（显示在边上）和 `condition`（Python 表达式或 "default"）
- 编译为 LangGraph `add_conditional_edges` 的 mapping

#### 人工确认节点 (`type: "human_confirm"`)

```json
{
  "id": "n3",
  "type": "human_confirm",
  "label": "人工审核",
  "position": {"x": 100, "y": 200},
  "config": {
    "message": "请审核生成的代码",
    "fields": [
      {"key": "approved", "label": "是否通过", "type": "boolean"},
      {"key": "comment", "label": "修改意见", "type": "text", "required": false}
    ],
    "timeout": 300
  }
}
```

- 编译时收集到 `interrupt_before` 列表
- 执行到该节点时暂停，SSE 推送 `human_confirm_required` 事件
- 前端弹出确认对话框，用户填写后 POST `/resume` 继续

#### 代码执行节点 (`type: "code"`)

```json
{
  "id": "n5",
  "type": "code",
  "label": "数据处理",
  "position": {"x": 400, "y": 350},
  "config": {
    "language": "python",
    "code": "import json\nresult = {'processed': state['raw_data']}\nreturn result",
    "timeout": 30,
    "output_key": "processed_data"
  }
}
```

- subprocess 沙箱执行，超时 kill
- `{state.xxx}` 模板变量在执行前注入
- stdout/stderr 通过 SSE `node_log` 事件实时推送

### 3.3 完整 IR 示例

```json
{
  "id": "wf-001",
  "name": "AI代码生成管线",
  "version": "1.0",
  "schema": {
    "input_schema": {
      "type": "object",
      "properties": {
        "requirement": {"type": "string"},
        "component_lib": {"type": "string", "default": "tailwind"}
      }
    },
    "state_variables": ["analysis_result", "code", "review_comment", "review_passed"]
  },
  "nodes": [
    {
      "id": "n1", "type": "llm", "label": "需求分析",
      "position": {"x": 100, "y": 50},
      "config": {
        "model": "glm-5.2",
        "system_prompt": "你是需求分析师...",
        "user_prompt": "分析: {state.requirement}",
        "output_key": "analysis_result"
      }
    },
    {
      "id": "n2", "type": "llm", "label": "代码生成",
      "position": {"x": 100, "y": 200},
      "config": {
        "model": "deepseek-v4",
        "system_prompt": "你是Vue3工程师...",
        "user_prompt": "根据分析生成代码:\n{state.analysis_result}",
        "output_key": "code"
      }
    },
    {
      "id": "n3", "type": "human_confirm", "label": "人工审核",
      "position": {"x": 100, "y": 350},
      "config": {
        "message": "请审核生成的代码",
        "fields": [
          {"key": "review_passed", "label": "是否通过", "type": "boolean"},
          {"key": "review_comment", "label": "修改意见", "type": "text", "required": false}
        ]
      }
    },
    {
      "id": "n4", "type": "router", "label": "判断结果",
      "position": {"x": 100, "y": 500},
      "config": {
        "branches": [
          {"label": "通过", "condition": "state.review_passed == true"},
          {"label": "需修改", "condition": "default"}
        ]
      }
    },
    {
      "id": "n5", "type": "code", "label": "格式化输出",
      "position": {"x": 400, "y": 500},
      "config": {
        "language": "python",
        "code": "import json\nreturn {'formatted': state['code']}",
        "output_key": "final_output"
      }
    }
  ],
  "edges": [
    {"id": "e1", "source": "n1", "target": "n2"},
    {"id": "e2", "source": "n2", "target": "n3"},
    {"id": "e3", "source": "n3", "target": "n4"},
    {"id": "e4", "source": "n4", "target": "n5", "condition": "通过"},
    {"id": "e5", "source": "n4", "target": "n2", "condition": "需修改"}
  ]
}
```

## 4. 系统架构

### 4.1 整体架构拓扑

```
┌─────────────────────────────────────────────────────────────────┐
│  ai-workflow (React + React Flow)                               │
│                                                                 │
│  ┌──────────────┐  ┌────────────┐  ┌──────────────────────┐    │
│  │ WorkflowCanvas│  │ NodePanel  │  │ RunMonitor           │    │
│  │ (拖拽/连线)   │  │ (节点配置) │  │ (执行状态/日志/预览) │    │
│  └──────┬───────┘  └─────┬──────┘  └──────────┬───────────┘    │
│         │                │                    │                │
│    Workflow IR ←─────────┘                    │ SSE 消费        │
│         │                                     │                │
│    POST /api/v1/workflow/save                 │                │
│    POST /api/v1/workflow/{id}/run  ───────────────────────────┘ │
└─────────┼─────────────────────────────────────┼────────────────┘
          │                                     │
┌─────────┼─────────────────────────────────────┼────────────────┐
│  ai-service (Python)                          │                │
│         │                                     │                │
│  ┌──────▼──────────┐  ┌──────────────────┐    │                │
│  │ WorkflowCompiler │  │ GraphRunner      │────┘                │
│  │ (IR→StateGraph)  │  │ (执行+SSE推送)   │                     │
│  └─────────────────┘  └────────┬─────────┘                     │
│                                │                               │
│  ┌─────────────────────────────▼──────────────────────────┐    │
│  │  Node Registry (节点类型注册表)                         │    │
│  │  ┌──────────┬──────────┬──────────┬──────────────┐    │    │
│  │  │LLMHandler│RouterHandler│HumanHandler│CodeHandler │    │    │
│  │  └──────────┴──────────┴──────────┴──────────────┘    │    │
│  └───────────────────────────────────────────────────────┘    │
│                                                                │
│  ┌───────────────────────────────────────────────────────┐    │
│  │  复用现有基础设施                                      │    │
│  │  AgentHarness (重试/追踪)  LoopControl (收敛/熔断)     │    │
│  │  EvalHarness (校验)       LLMProvider (多模型)        │    │
│  └───────────────────────────────────────────────────────┘    │
└────────────────────────────────────────────────────────────────┘
```

### 4.2 组件职责

#### 新增模块

| 模块 | 位置 | 职责 |
|------|------|------|
| `compiler.py` | ai-service | Workflow IR → LangGraph StateGraph 编译 |
| `registry.py` | ai-service | 节点类型 → Handler 映射注册表 |
| `handlers/` | ai-service | 每种节点类型的执行逻辑 |
| `sandbox.py` | ai-service | Python/JS 代码安全执行（subprocess 隔离） |
| `components/` (React) | ai-workflow | React Flow 节点/边/面板组件 |
| `composables/` (React) | ai-workflow | useWorkflow, useWorkflowRun hooks |

#### 修改现有模块

| 模块 | 变更 |
|------|------|
| `graph.py` | 从硬编码 5 节点 → 接受动态 nodes/edges 构建（`build_graph_from_ir()`） |
| `nodes.py` | 现有节点逻辑提取为 Handler 基类，通过 registry 注册 |
| `servicer.py` | 新增 save/list/get/run/resume/cancel 接口 |
| `workflowSlice.ts` | 扩展 state 支持画布数据（nodes/edges/workflowIR） |
| `ai-workflow/src/` | 从空壳 → 完整工作流编辑器和运行器 |

### 4.3 节点 Handler 注册机制

```python
# registry.py
class NodeHandler(ABC):
    """节点处理器基类"""
    node_type: str

    @abstractmethod
    async def execute(self, state: dict, config: dict) -> dict:
        """执行节点逻辑，返回 state 更新"""

    @abstractmethod
    def compile_to_langgraph(self, node_def: NodeDef) -> Callable:
        """将节点定义编译为 LangGraph node function"""

# 注册
NodeRegistry.register(LLMHandler())         # 复用 _llm_generate
NodeRegistry.register(RouterHandler())      # 编译为 conditional edge
NodeRegistry.register(HumanConfirmHandler()) # interrupt_before
NodeRegistry.register(CodeHandler())        # 沙箱执行

# 使用
compiler = WorkflowCompiler(registry)
app = compiler.compile(workflow_ir)  # → StateGraph
```

新增节点类型只需:
1. 实现 `NodeHandler` 子类
2. 调用 `NodeRegistry.register()`
3. 前端在 NodePalette 中注册图标和配置表单 schema

## 5. 前端设计

### 5.1 页面布局（三栏结构）

```
┌─────────────┬──────────────────────────┬────────────────┐
│ NodePalette │    WorkflowCanvas        │ NodeConfigPanel│
│ (200px)     │    (flex: 1)             │ (320px)        │
│             │                          │                │
│ 节点工具箱   │  ┌─────┐    ┌─────┐     │ 节点配置表单    │
│ 🧠 LLM     │  │ n1  │───▶│ n2  │     │                │
│ 🔀 Router   │  └─────┘    └─────┘     │ Model: [____]  │
│ ✋ Human    │       │         │        │ Prompt: [____] │
│ ⚡ Code     │       │    ┌────▼────┐   │ Temp: [===⭘=] │
│             │       └───▶│   n3    │   │                │
│ ────────── │            └─────────┘   │                │
│ 工作流列表   │                          │                │
│ wf-1       │   ▶ Run  💾 Save  ↩ Undo │                │
│ wf-2       │                          │                │
└─────────────┴──────────────────────────┴────────────────┘
```

### 5.2 组件树

```
WorkflowView (页面容器)
├── WorkflowToolbar       — 运行/保存/撤销/缩放控制
├── WorkflowLayout        — 三栏布局容器
│   ├── NodePalette       — 左侧：可拖拽节点类型列表 + 工作流列表
│   ├── WorkflowCanvas    — 中间：React Flow 画布
│   │   ├── BaseNode      — 通用节点渲染（图标/标签/状态灯/输入输出handle）
│   │   ├── WorkflowEdge  — 自定义边（条件标签/动画/删除按钮）
│   │   └── Minimap       — 画布缩略图
│   └── NodeConfigPanel   — 右侧：节点配置表单（按 type 动态渲染）
└── RunOverlay            — 运行时覆盖层（节点状态高亮/动画/日志流）
```

### 5.3 交互设计

| 交互 | 说明 |
|------|------|
| 拖拽添加节点 | 从 NodePalette 拖到画布，自动生成唯一 id 和默认位置 |
| 连线 | 从 output handle 拖线到目标 input handle；条件路由节点出边可设置 condition label |
| 节点配置 | 点击节点 → 右侧面板动态渲染对应 type 的配置表单 |
| 运行反馈 | 执行时画布显示节点状态（pending→running→done→error），高亮当前节点，SSE 事件驱动 |

### 5.4 技术选型

| 层 | 选型 | 理由 |
|----|------|------|
| 画布引擎 | React Flow (@xyflow/react) | 最成熟的 React 节点编辑器库，内置 drag/drop/zoom/minimap |
| 状态管理 | Redux Toolkit (已有) | ai-workflow 已用 Redux，扩展 workflowSlice |
| UI 样式 | Tailwind CSS (已有) | 项目已配置 Tailwind |
| SSE 客户端 | event-source-polyfill | 与 ai-generation-app 保持一致 |

## 6. 执行引擎设计

### 6.1 编译流程: Workflow IR → StateGraph

```
Step 1: 解析 state_variables → 动态构建 GenerationState TypedDict fields
Step 2: 遍历 nodes, 每个 node → registry.lookup(type) 获取 handler
Step 3: handler.compile(node_def) → add_node(node_id, handler_fn)
Step 4: 遍历 edges, 普通边 → add_edge, 条件边 → add_conditional_edges
Step 5: 收集 human_confirm 节点 id → compile(checkpointer, interrupt_before=[...])
```

### 6.2 节点编译策略

| 节点类型 | 编译为 LangGraph 的什么 | 关键处理 |
|---------|----------------------|---------|
| LLM | `add_node(id, llm_handler)` | handler 调用 `_llm_generate`，prompt 模板变量从 state 解析 |
| Router | `add_conditional_edges(source, router_fn, mapping)` | 条件表达式用 Python `eval()` 在受限 namespace 中计算 |
| Human Confirm | 收集 node_id → `interrupt_before` | SSE 推送确认请求 → 等待 HTTP POST resume |
| Code | `add_node(id, sandbox_handler)` | subprocess 沙箱执行，超时 kill，stdout/stderr → SSE node_log |

### 6.3 SSE 事件协议

| 事件 | 方向 | 载荷 | 前端行为 |
|------|------|------|---------|
| `workflow_start` | ← | {workflow_id, nodes_count} | 画布进入 RunOverlay，所有节点置为 pending |
| `stage_start` | ← | {node_id, label, timestamp} | 节点高亮为 running（脉冲动画） |
| `stage_complete` | ← | {node_id, summary, output_preview} | 节点变绿 ✓，显示 output_preview |
| `human_confirm_required` | ← | {node_id, message, fields} | 节点闪烁，弹出确认对话框 |
| `node_log` | ← | {node_id, level, message} | 追加到运行日志面板 |
| `node_error` | ← | {node_id, error, retry_count} | 节点变红 ✗，显示错误信息 |
| `workflow_complete` | ← | {status, total_tokens, duration_ms} | 退出 RunOverlay，弹出汇总 |
| `workflow_resume` | → | POST {node_id, response} | 用户在确认框填写后发送 |

**时序示例:**

```
POST /api/v1/workflow/{id}/run  ──────▶  GraphRunner.run(workflow_ir)
  ◀── SSE: workflow_start
  ◀── SSE: stage_start {n1, "需求分析"}
  ◀── SSE: stage_complete {n1, ...}
  ◀── SSE: stage_start {n2, "代码生成"}
  ◀── SSE: stage_complete {n2, ...}
  ◀── SSE: human_confirm_required {n3, "请审核", [...]}
  ⏸️  等待用户...
POST /api/v1/workflow/{id}/resume ────▶  app.update_state() + continue
  ◀── SSE: stage_start {n4, "判断结果"}
  ◀── SSE: stage_complete {n4, ...}
  ◀── SSE: workflow_complete {ok, ...}
```

### 6.4 HTTP API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/workflow/save` | 保存工作流定义（Workflow IR JSON） |
| GET | `/api/v1/workflow/list` | 列出所有工作流 |
| GET | `/api/v1/workflow/{id}` | 获取工作流详情 |
| POST | `/api/v1/workflow/{id}/run` | 运行工作流（返回 SSE 流） |
| POST | `/api/v1/workflow/{id}/resume` | 恢复暂停的工作流 |
| POST | `/api/v1/workflow/{id}/cancel` | 取消运行 |

## 7. 复用现有基础设施

| 现有模块 | 复用方式 |
|---------|---------|
| `AgentHarness` | LLM Handler 和 Code Handler 通过 harness 执行（重试/追踪/schema 校验） |
| `LoopControl` | 集成到 GraphRunner，追踪 rollback 次数，触发熔断 |
| `EvalHarness` | Code Handler 执行后运行确定性校验 |
| `LLMProvider` | LLM Handler 直接调用，支持多模型切换 |
| `GraphSSEHandler` (Gateway) | 复用 SSE 事件转发机制 |
| `_llm_generate()` | LLM Handler 的核心调用函数 |
| `GenerationState` | 动态构建基础（加入 state_variables 中声明的字段） |

## 8. 安全考量

### 8.1 代码执行沙箱

- subprocess 隔离，非容器化
- 超时 kill（默认 30s，最大 120s）
- 禁止的网络访问、文件系统写入限制
- 可用模块白名单

### 8.2 条件表达式安全

- Router 的 `condition` 表达式在受限 `eval()` namespace 中执行
- 只允许访问 `state` 字典和基本运算符
- 禁止 `__import__`、`open`、`exec` 等危险函数

### 8.3 Prompt 注入防护

- `{state.xxx}` 模板变量做 HTML/JS 转义
- 不直接将用户输入拼接到 system prompt

## 9. 实施路径

分三个阶段渐进式实施:

### Phase 1: 后端核心 — Workflow IR 编译 + 执行链路

- 实现 `compiler.py`（IR → StateGraph）
- 实现 `registry.py` + 4 种 Handler（LLM/Router/HumanConfirm/Code）
- 实现 `sandbox.py`（Python/JS 沙箱）
- 扩展 `servicer.py` 新增 API
- 扩展 `graph.py` 的 `GraphRunner` 支持动态图
- **验证标准**: 用 Python 脚本构造 Workflow IR JSON，后端能编译并执行完整流程，SSE 事件正常推送

### Phase 2: 前端画布 — React Flow 编辑器

- 集成 React Flow，实现 `WorkflowCanvas`、`BaseNode`、`WorkflowEdge`
- 实现 `NodePalette`（拖拽添加节点）
- 实现 `NodeConfigPanel`（按 type 动态渲染配置表单）
- 实现 Workflow IR 序列化/反序列化
- **验证标准**: 在画布上自由拖拽 4 种节点、连线、配置属性，点击保存生成正确的 Workflow IR JSON

### Phase 3: 前后端联通 — 运行监控 + Human-in-the-loop

- 实现 SSE 消费层（`useWorkflowRun` hook）
- 实现 `RunOverlay`（节点状态高亮/动画）
- 实现人工确认对话框
- 实现运行日志面板
- 端到端联调
- **验证标准**: 画布设计工作流 → 点击运行 → 观察节点逐个执行 → 人工确认弹框 → 继续执行 → 完成

## 10. 文件改动清单

### 后端新增

| 文件 | 说明 |
|------|------|
| `ai-service/app/services/workflow/__init__.py` | 新 package |
| `ai-service/app/services/workflow/compiler.py` | Workflow IR → StateGraph 编译器 |
| `ai-service/app/services/workflow/registry.py` | 节点类型注册表 |
| `ai-service/app/services/workflow/handlers/__init__.py` | Handler 基类 |
| `ai-service/app/services/workflow/handlers/llm_handler.py` | LLM 节点处理器 |
| `ai-service/app/services/workflow/handlers/router_handler.py` | 条件路由处理器 |
| `ai-service/app/services/workflow/handlers/human_handler.py` | 人工确认处理器 |
| `ai-service/app/services/workflow/handlers/code_handler.py` | 代码执行处理器 |
| `ai-service/app/services/workflow/sandbox.py` | 代码沙箱 |
| `ai-service/app/services/workflow/servicer.py` | gRPC servicer |
| `ai-service/tests/test_compiler.py` | 编译器测试 |
| `ai-service/tests/test_handlers.py` | Handler 测试 |

### 后端修改

| 文件 | 变更 |
|------|------|
| `ai-service/app/services/generation/graph.py` | GraphRunner 重构为接受动态 node/edge |
| `ai-service/app/services/generation/nodes.py` | 提取 Handler 基类 |
| `ai-service/app/services/generation/servicer.py` | 新增 workflow API |

### 前端新增

| 文件 | 说明 |
|------|------|
| `ai-workflow/src/components/WorkflowCanvas.tsx` | React Flow 画布 |
| `ai-workflow/src/components/nodes/BaseNode.tsx` | 通用节点组件 |
| `ai-workflow/src/components/nodes/LLMNode.tsx` | LLM 节点样式 |
| `ai-workflow/src/components/nodes/RouterNode.tsx` | 路由节点样式 |
| `ai-workflow/src/components/nodes/HumanNode.tsx` | 人工确认节点样式 |
| `ai-workflow/src/components/nodes/CodeNode.tsx` | 代码节点样式 |
| `ai-workflow/src/components/edges/WorkflowEdge.tsx` | 自定义边 |
| `ai-workflow/src/components/panels/NodePalette.tsx` | 节点工具箱 |
| `ai-workflow/src/components/panels/NodeConfigPanel.tsx` | 节点配置面板 |
| `ai-workflow/src/components/panels/RunOverlay.tsx` | 运行时覆盖层 |
| `ai-workflow/src/components/WorkflowToolbar.tsx` | 工具栏 |
| `ai-workflow/src/composables/useWorkflow.ts` | 工作流 CRUD hook |
| `ai-workflow/src/composables/useWorkflowRun.ts` | SSE 运行监控 hook |
| `ai-workflow/src/composables/useNodeDrag.ts` | 拖拽添加节点 hook |
| `ai-workflow/src/types/workflow.ts` | 前端类型定义 |

### 前端修改

| 文件 | 变更 |
|------|------|
| `ai-workflow/src/store/slices/workflowSlice.ts` | 扩展画布相关 state |
| `ai-workflow/src/App.tsx` | 路由调整 |
| `ai-workflow/src/pages/Home.tsx` | 替换为 WorkflowView |
| `ai-workflow/src/router/index.tsx` | 新增路由 |
| `ai-workflow/package.json` | 添加 @xyflow/react 依赖 |
