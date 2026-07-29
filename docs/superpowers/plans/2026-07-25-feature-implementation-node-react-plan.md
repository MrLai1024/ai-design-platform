# 功能实现节点 ReAct 模式 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 code node 升级为全自主 ReAct 双层智能体（Planner 任务规划 + Executor 逐任务生成），集成上下文管理、Chunk 级 HMR 编译渲染、qiankun 微应用工程生成。

**Architecture:** 新增 `planner.py`（Planner Agent + Task DAG）、`context_manager.py`（上下文压缩/检索）、`contract_verifier.py`（接口契约校验），改造 `nodes.py`（code_node → planner_node + executor_task），扩展 `PreviewFrame`（iframe 内 IncrementalCompiler + ModuleRegistry + HotReloader）、`AgentLog`（task 分组展示），新增 Skill `qiankun-app.json`。

**Tech Stack:** Python 3.13 (LangGraph + asyncio), Vue 3 (Composition API + Pinia), TypeScript, iframe sandbox JS

---

## File Structure

```
后端新建:
  ai-service/app/services/generation/planner.py         — Planner Agent: REASON→ACT(DAG)→OBSERVE→REFLECT
  ai-service/app/services/generation/context_manager.py — 上下文压缩/检索工具
  ai-service/app/services/generation/contract_verifier.py — 接口契约校验工具

后端修改:
  ai-service/app/services/generation/state.py           — 新增 TaskDAG 类型
  ai-service/app/services/generation/nodes.py           — 新增 planner_node, executor_task 函数
  ai-service/app/services/generation/graph.py           — Phase 3 改为 planner+executor 流
  ai-service/app/services/generation/tools/registry.py  — 注册新工具 (summarize_context, retrieve_context, verify_contract)
  ai-service/app/services/generation/tools/mcp_bridge.py — 升级为真实 MCP 连接
  ai-service/app/services/generation/tools/skill_loader.py — 支持 contract 字段

后端新增 Skill:
  ai-service/app/services/generation/skills/qiankun-app.json — 微应用生命周期模板

前端修改:
  packages/ai-generation-app/src/types/generation.ts     — 新增 PlannerTask, TaskGroup, HmrEvent 类型
  packages/ai-generation-app/src/stores/generation.ts    — 新增 taskGroups, hmrRegistry state
  packages/ai-generation-app/src/components/AgentLog.vue — 新增 task 分组卡片
  packages/ai-generation-app/src/components/PreviewFrame.vue — 集成 HMR runtime
  packages/ai-generation-app/src/composables/useCodeStream.ts — 新增 planner/task 事件处理
  packages/ai-generation-app/src/composables/usePreviewRenderer.ts — 新增 chunk 级更新 + HMR 消息

前端新增:
  packages/ai-generation-app/src/utils/hmrRuntime.ts    — iframe 内注入的 HMR runtime 脚本
```

---

## Phase 1: Planner Agent + Task DAG 后端实现

### Task 1: 扩展 state.py — 新增 Task DAG 类型

**Files:**
- Modify: `ai-design-platform-server/ai-service/app/services/generation/state.py`

- [ ] **Step 1: 新增 PlannerTask 和 TaskDAG TypedDict**

在 `GenerationState` 定义之前插入：

```python
from typing import TypedDict, Literal, NotRequired


class PlannerTask(TypedDict):
    id: str                          # "task-0", "task-1", ...
    type: Literal["bootstrap", "business"]
    description: str                 # 人类可读描述
    deps: list[str]                  # 依赖的 task id 列表
    files: list[str]                 # 需要生成的文件路径
    contract: dict                   # { exports: [...], props: {...}, events: [...] }
    status: Literal["pending", "running", "done", "failed"]
    executor_summary: NotRequired[str]
    compile_errors: NotRequired[list[dict]]


class TaskDAG(TypedDict):
    tasks: list[PlannerTask]
    generated_at: str
    total_tasks: int
    completed_tasks: int
```

- [ ] **Step 2: 在 GenerationState 中新增字段**

在 `GenerationState` TypedDict 末尾（`e2e_user_confirmed` 之后）新增：

```python
    # ====== Planner + Executor ReAct fields ======
    planner_dag: TaskDAG | None                    # Planner 输出的任务 DAG
    planner_reflect_count: int                     # Planner 重规划次数
    context_summary: dict | None                   # 全局摘要 {key_exports: {...}, completed_tasks: [...]}
```

- [ ] **Step 3: 验证**

```bash
cd ai-design-platform-server/ai-service
python -c "from app.services.generation.state import GenerationState, PlannerTask, TaskDAG; print('OK')"
```

---

### Task 2: 创建 planner.py — Planner Agent

**Files:**
- Create: `ai-design-platform-server/ai-service/app/services/generation/planner.py`

- [ ] **Step 1: 写入 Planner System Prompt 和核心函数**

```python
"""Planner Agent — REASON→ACT(DAG)→OBSERVE→REFLECT loop for task decomposition."""

import json
import structlog

logger = structlog.get_logger()

PLANNER_SYSTEM_PROMPT = """你是一个资深前端工程架构师，负责将设计文档拆解为可独立执行的任务。

## 你的职责
1. 分析设计文档，识别组件依赖树、数据流、路由结构
2. 将工程拆解为有序任务（Task DAG），每个任务是独立可执行单元
3. 对每个 task 定义接口契约（exports/props/events/slots）
4. 接收执行反馈后动态调整计划

## 任务类型
- **bootstrap**: 工程脚手架任务（qiankun 生命周期、webpack 配置、package.json）
- **business**: 业务功能任务（组件、页面、状态管理、API 层）

## 输出格式
输出严格 JSON，格式为：
```json
{
  "reasoning": "任务拆解思路...",
  "tasks": [
    {
      "id": "task-0",
      "type": "bootstrap",
      "description": "qiankun 微应用入口",
      "deps": [],
      "files": ["src/main.ts", "src/public-path.ts"],
      "contract": {
        "exports": ["bootstrap", "mount", "unmount"]
      }
    },
    {
      "id": "task-1",
      "type": "bootstrap",
      "description": "webpack + package 配置",
      "deps": [],
      "files": ["webpack/webpack.common.js", "package.json", "tsconfig.json"],
      "contract": { "exports": [] }
    },
    {
      "id": "task-2",
      "type": "business",
      "description": "根组件 App.vue + 路由配置",
      "deps": ["task-0"],
      "files": ["src/App.vue", "src/router/index.ts"],
      "contract": {
        "exports": ["App"],
        "components": ["router-view"],
        "routes": ["/" ]
      }
    }
  ]
}
```

## 规则
- 总是包含 3 个 bootstrap 任务（qiankun 入口、webpack 配置、package 配置）
- 每个 task 文件数不超过 5 个
- 依赖关系必须是有向无环图（DAG）
- task id 从 "task-0" 开始递增
- 只输出 JSON，不要额外文本
"""

PLANNER_REFLECT_PROMPT = """你是一个资深前端工程架构师。根据执行反馈调整任务计划。

## 当前 DAG 状态
{current_dag}

## 执行反馈
{execution_feedback}

## 已有文件摘要
{context_summary}

## 任务
分析执行反馈，决定下一步：
1. 所有任务完成且编译通过 → 输出 {"decision": "done", "reason": "..."}
2. 部分任务失败 → 输出修正后的 DAG（只包含未完成/失败的任务）：{"decision": "replan", "tasks": [...]}
3. 需要重试失败任务 → {"decision": "retry", "task_ids": ["task-3"], "adjustments": "..."}
4. 阻塞无法继续 → {"decision": "blocked", "reason": "...", "suggestion": "..."}

只输出 JSON。
"""


def extract_task_dag(raw_json: str) -> dict:
    """Parse Planner LLM output into TaskDAG dict."""
    # Strip markdown code fences if present
    cleaned = raw_json.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned.split("```json", 1)[1]
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```", 1)[1]
    if cleaned.endswith("```"):
        cleaned = cleaned.rsplit("```", 1)[0]
    cleaned = cleaned.strip()

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.error("planner_json_parse_failed", raw=cleaned[:200])
        raise

    # Validate and normalize tasks
    tasks = parsed.get("tasks", [])
    for t in tasks:
        t.setdefault("status", "pending")
        t.setdefault("type", "business")
        t.setdefault("deps", [])
        t.setdefault("contract", {})

    return {
        "reasoning": parsed.get("reasoning", ""),
        "tasks": tasks,
    }


def extract_reflect_decision(raw_json: str) -> dict:
    """Parse Planner reflect decision."""
    cleaned = raw_json.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned.split("```json", 1)[1]
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```", 1)[1]
    if cleaned.endswith("```"):
        cleaned = cleaned.rsplit("```", 1)[0]
    cleaned = cleaned.strip()

    return json.loads(cleaned)


def build_planner_user_prompt(design_doc: str, failure: dict | None = None) -> str:
    """Build the user prompt for the Planner's initial reasoning."""
    if failure:
        return (
            f"设计方案：\n{design_doc}\n\n"
            f"之前的代码存在问题：\n{failure.get('instruction', '')}\n\n"
            f"请重新规划任务。"
        )
    return (
        f"设计方案：\n{design_doc}\n\n"
        f"请拆解为可独立执行的任务。记住：必须包含 qiankun 微应用必需的 3 个 bootstrap 任务。"
    )
```

- [ ] **Step 2: 验证**

```bash
cd ai-design-platform-server/ai-service
python -c "
from app.services.generation.planner import extract_task_dag, build_planner_user_prompt
print('OK')
"
```

---

### Task 3: 创建 context_manager.py — 上下文管理工具

**Files:**
- Create: `ai-design-platform-server/ai-service/app/services/generation/context_manager.py`

- [ ] **Step 1: 写入上下文压缩与检索逻辑**

```python
"""Context Manager — summarize and retrieve context for LLM sessions."""

import re
import structlog
from .tools.registry import ToolResult

logger = structlog.get_logger()

# Match Vue SFC exports: export default defineComponent, defineProps, defineEmits
_EXPORT_RE = re.compile(
    r'(export\s+(?:default\s+)?(?:defineComponent|function|class|const|let|var)\s+(\w+))|'
    r'(defineProps<([^>]+)>)|'
    r'(defineEmits<([^>]+)>)',
    re.MULTILINE,
)


def extract_interface_contract(file_path: str, content: str) -> dict:
    """Extract exports/props/events from a source file using regex (rule-engine, no LLM)."""
    contract = {
        "file": file_path,
        "exports": [],
        "props": None,
        "events": [],
    }

    for match in _EXPORT_RE.finditer(content):
        if match.group(2):  # export const/function/class name
            contract["exports"].append(match.group(2))
        if match.group(3):  # defineProps<...>
            contract["props"] = match.group(3).strip()
        if match.group(4):  # defineEmits<...>
            events_str = match.group(5).strip()  # actually group 5 for defineEmits
            contract["events"] = [e.strip() for e in events_str.split(",")]
        if match.group(5) and not match.group(4):
            # defineEmits match — match.group(5) has the inner type
            pass

    # Also check defineEmits specifically
    for m in re.finditer(r'defineEmits<([^>]+)>', content):
        contract["events"] = [e.strip() for e in m.group(1).split(",")]

    return contract


async def summarize_context(files: dict[str, str], max_tokens: int = 8000) -> ToolResult:
    """
    Compress generated files into structured summary.
    Uses rule-engine for contract extraction (no LLM tokens consumed).
    """
    summary_parts = []
    key_exports = {}
    total_lines = 0
    dropped_details = []

    for path, content in files.items():
        lines = content.count("\n") + 1
        total_lines += lines
        contract = extract_interface_contract(path, content)
        key_exports[path] = contract

        summary_parts.append(
            f"- {path}: {lines} lines, "
            f"exports={contract['exports']}, "
            f"props={contract['props']}, "
            f"events={contract['events']}"
        )

        if lines > 300:
            dropped_details.append({
                "file": path,
                "reason": f"Large file ({lines} lines), only interface contract retained",
            })

    summary = {
        "total_files": len(files),
        "total_lines": total_lines,
        "key_exports": key_exports,
        "file_list": summary_parts,
        "dropped_details": dropped_details,
    }

    return ToolResult(ok=True, data=summary)


async def retrieve_context(files: dict[str, str], query: str) -> ToolResult:
    """
    Search generated files for relevant context matching the query.
    Simple keyword-based retrieval (upgradeable to embedding-based).
    """
    query_lower = query.lower()
    query_terms = query_lower.split()
    results = []

    for path, content in files.items():
        content_lower = content.lower()
        score = sum(1 for term in query_terms if term in content_lower)
        if score > 0 or any(term in path.lower() for term in query_terms):
            # Extract relevant snippet
            idx = content_lower.find(query_terms[0]) if query_terms else 0
            start = max(0, idx - 100)
            end = min(len(content), idx + 500)
            snippet = content[start:end]
            results.append({
                "file": path,
                "content_snippet": snippet,
                "relevance": score,
            })

    results.sort(key=lambda r: r["relevance"], reverse=True)
    return ToolResult(ok=True, data={"results": results[:10]})


async def verify_contract(
    files: dict[str, str],
    consumer_file: str,
    provider_file: str,
    expected_interface: dict,
) -> ToolResult:
    """
    Verify that consumer_file correctly uses provider_file's exports.
    Checks: props match, event names match.
    """
    consumer_content = files.get(consumer_file, "")
    provider_content = files.get(provider_file, "")

    if not consumer_content or not provider_content:
        return ToolResult(ok=False, error="File not found in generated files")

    provider_contract = extract_interface_contract(provider_file, provider_content)
    violations = []

    # Check props
    expected_props = expected_interface.get("props", {})
    if expected_props and provider_contract["props"]:
        # Simple check: expected prop names exist in consumer usage
        for prop_name in expected_props:
            if prop_name not in consumer_content:
                violations.append({
                    "type": "missing_prop",
                    "detail": f"{consumer_file} may not pass prop '{prop_name}' to {provider_file}",
                })

    # Check exports
    expected_exports = expected_interface.get("exports", [])
    for export_name in expected_exports:
        if export_name not in provider_contract["exports"]:
            violations.append({
                "type": "missing_export",
                "detail": f"{provider_file} missing expected export '{export_name}'",
            })

    match = len(violations) == 0
    return ToolResult(ok=True, data={"match": match, "violations": violations})
```

- [ ] **Step 2: 验证**

```bash
cd ai-design-platform-server/ai-service
python -c "
from app.services.generation.context_manager import summarize_context, retrieve_context, verify_contract, extract_interface_contract
print('OK')
"
```

---

### Task 4: 注册新工具到 ToolRegistry

**Files:**
- Modify: `ai-design-platform-server/ai-service/app/services/generation/tools/registry.py`

- [ ] **Step 1: 在 `_register_builtins` 方法末尾追加新工具注册**

在 `_register_builtins` 的 `self.register(...)` for `list_skills` 之后追加：

```python
        from ..context_manager import summarize_context as _summarize_ctx
        from ..context_manager import retrieve_context as _retrieve_ctx
        from ..context_manager import verify_contract as _verify_contract

        self.register(ToolDef(
            name="summarize_context",
            description="将已生成的文件压缩为结构化摘要，释放上下文窗口。用于上下文过长时降低 token 消耗。",
            parameters={
                "type": "object",
                "properties": {
                    "max_tokens": {
                        "type": "integer",
                        "description": "摘要目标 token 数，默认 8000",
                        "default": 8000,
                    },
                },
            },
            handler=lambda **kw: _summarize_ctx(self._generated_files or {}, **kw),
            category="context",
        ))

        self.register(ToolDef(
            name="retrieve_context",
            description="从已生成文件中检索相关上下文。用于需要了解其他文件接口时按需查询。",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索查询，如 'Header props 定义'"},
                },
                "required": ["query"],
            },
            handler=lambda **kw: _retrieve_ctx(self._generated_files or {}, **kw),
            category="context",
        ))

        self.register(ToolDef(
            name="verify_contract",
            description="校验两个文件之间的接口契约是否一致。用于验证消费者组件正确使用了提供者组件的导出。",
            parameters={
                "type": "object",
                "properties": {
                    "consumer_file": {"type": "string", "description": "消费方文件路径"},
                    "provider_file": {"type": "string", "description": "提供方文件路径"},
                    "expected_interface": {
                        "type": "object",
                        "description": "期望的接口定义，如 {props: ['title'], events: ['submit']}",
                    },
                },
                "required": ["consumer_file", "provider_file"],
            },
            handler=lambda **kw: _verify_contract(self._generated_files or {}, **kw),
            category="context",
        ))
```

- [ ] **Step 2: 在 ToolRegistry.__init__ 中添加 `_generated_files` 属性**

在 `__init__` 方法的 `self._register_builtins()` 之前添加：

```python
        self._generated_files: dict[str, str] = {}
```

- [ ] **Step 3: 添加 `set_generated_files` 方法**

在 `invoke` 方法之后添加：

```python
    def set_generated_files(self, files: dict[str, str]) -> None:
        """Update the generated files cache for context tools."""
        self._generated_files = files
```

- [ ] **Step 4: 验证**

```bash
cd ai-design-platform-server/ai-service
python -c "
from app.services.generation.tools.registry import ToolRegistry
r = ToolRegistry('/tmp/test')
schema = r.get_schema()
names = [t['function']['name'] for t in schema]
assert 'summarize_context' in names
assert 'retrieve_context' in names
assert 'verify_contract' in names
print('OK — Tools registered:', names)
"
```

---

### Task 5: 改造 nodes.py — 新增 planner_node + executor_task

**Files:**
- Modify: `ai-design-platform-server/ai-service/app/services/generation/nodes.py`

- [ ] **Step 1: 在文件顶部追加 imports**

在现有 imports 之后追加：

```python
from .planner import (
    PLANNER_SYSTEM_PROMPT,
    PLANNER_REFLECT_PROMPT,
    extract_task_dag,
    extract_reflect_decision,
    build_planner_user_prompt,
)
from .context_manager import extract_interface_contract
```

- [ ] **Step 2: 新增 EXECUTOR_SYSTEM_PROMPT**

在 `CODE_ORCHESTRATOR_PROMPT` 之后追加：

```python
EXECUTOR_SYSTEM_PROMPT = """你是一个 Vue 3 前端工程师，负责完成一个具体的代码生成任务。

## 任务信息
你会收到一个具体的 task，包含：
- 任务描述
- 需要生成的文件列表
- 接口契约（exports/props/events 要求）
- 依赖文件的接口摘要

## 工作流程
1. 理解任务目标和接口契约
2. 调用 use_skill 或 mcp_query 获取模板和文档
3. 调用 write_code 逐个生成文件
4. 全部文件生成后调用 compile_project 检查
5. 有编译错误时修复后再 compile
6. 编译通过后输出 __TASK_DONE__

## 规则
- 只生成该 task 范围内的文件
- 遵守接口契约，确保导出的 props/events/slots 与契约一致
- 每次只做一件事
- 组件名使用 PascalCase，文件名使用 kebab-case
- 使用 Vue 3 Composition API (`<script setup lang="ts">`)
- 确保每个 .vue 文件有完整的 `<template>`、`<script setup>`、`<style scoped>`
- 工具调用的 arguments 必须是合法 JSON 字符串
"""
```

- [ ] **Step 3: 新增 planner_node 函数**

在 `code_node_streaming` 函数之后、`_estimate_files` 之前插入：

```python
async def planner_node(
    state: GenerationState,
    queue,
) -> GenerationState:
    """Planner Agent — REASON→ACT: 解析设计文档，输出 Task DAG."""
    logger.info("planner_node_start")

    design_doc = state.get("design_doc") or state.get("design_result", "")
    failure = state.get("failure_details")
    reflect_count = state.get("planner_reflect_count", 0)

    user_prompt = build_planner_user_prompt(design_doc, failure)

    # REASON + ACT: 一次性输出 DAG
    def on_thinking(text: str):
        queue.put_nowait(_make_queue_event("thinking_chunk", "code", {"text": text}))

    queue.put_nowait(_make_queue_event("planner_start", "code", {
        "phase": "planning",
        "message": "正在分析设计方案，拆解任务...",
    }))

    raw_response = await _llm_generate(
        system_prompt=PLANNER_SYSTEM_PROMPT,
        user_content=user_prompt,
        enable_thinking=True,
        on_reasoning=on_thinking,
    )

    try:
        dag = extract_task_dag(raw_response)
    except Exception as e:
        logger.error("planner_extract_failed", error=str(e))
        # Fallback: minimal DAG with code generation task
        dag = {
            "reasoning": "Fallback due to parse error",
            "tasks": [
                {
                    "id": "task-bootstrap-0",
                    "type": "bootstrap",
                    "description": "qiankun lifecycle entry",
                    "deps": [],
                    "files": ["src/main.ts", "src/public-path.ts"],
                    "contract": {"exports": ["bootstrap", "mount", "unmount"]},
                    "status": "pending",
                },
                {
                    "id": "task-bootstrap-1",
                    "type": "bootstrap",
                    "description": "webpack + package config",
                    "deps": [],
                    "files": ["webpack/webpack.common.js", "package.json", "tsconfig.json"],
                    "contract": {"exports": []},
                    "status": "pending",
                },
                {
                    "id": "task-code-0",
                    "type": "business",
                    "description": "Main app component and all business code",
                    "deps": ["task-bootstrap-0"],
                    "files": _estimate_files(design_doc),
                    "contract": {"exports": ["App"]},
                    "status": "pending",
                },
            ],
        }

    task_dag = {
        "tasks": dag["tasks"],
        "generated_at": str(round(__import__("time").time())),
        "total_tasks": len(dag["tasks"]),
        "completed_tasks": 0,
    }

    queue.put_nowait(_make_queue_event("planner_dag", "code", {
        "tasks": dag["tasks"],
        "reasoning": dag.get("reasoning", ""),
    }))

    state["planner_dag"] = task_dag
    state["planner_reflect_count"] = reflect_count
    state["context_summary"] = {"key_exports": {}, "completed_tasks": []}
    state["generated_files"] = {}

    return state
```

- [ ] **Step 4: 新增 executor_task 函数**

在 `planner_node` 之后插入：

```python
async def executor_task(
    state: GenerationState,
    task: dict,
    queue,
    project_root: str,
    registry,
) -> dict:
    """
    Executor Agent — 为单个 task 运行 REASON→ACT→OBSERVE→REFLECT loop.
    Returns: {task_id, status, generated_files, compile_errors, summary}
    """
    task_id = task["id"]
    logger.info("executor_task_start", task_id=task_id, desc=task.get("description", ""))

    queue.put_nowait(_make_queue_event("task_start", "code", {
        "task_id": task_id,
        "description": task.get("description", ""),
        "files": task.get("files", []),
    }))

    # Build Executor context — include dependency contracts from context_summary
    context_summary = state.get("context_summary", {})
    deps_info = ""
    for dep_id in task.get("deps", []):
        for t in state.get("planner_dag", {}).get("tasks", []):
            if t["id"] == dep_id and t.get("status") == "done":
                deps_info += f"\n依赖 {dep_id} ({t['description']}): {json.dumps(t.get('contract', {}), ensure_ascii=False)}"
                # Include key exports for dependency files
                for f in t.get("files", []):
                    if f in context_summary.get("key_exports", {}):
                        deps_info += f"\n  {f} 接口: {json.dumps(context_summary['key_exports'][f], ensure_ascii=False)}"

    files_to_generate = task.get("files", [])
    contract = task.get("contract", {})

    system_prompt = EXECUTOR_SYSTEM_PROMPT
    user_msg = (
        f"## 任务\n{task.get('description', '')}\n\n"
        f"## 需要生成的文件\n{json.dumps(files_to_generate, ensure_ascii=False)}\n\n"
        f"## 接口契约要求\n{json.dumps(contract, ensure_ascii=False)}"
        f"{deps_info}\n\n"
        f"开始生成。先调用 list_skills 了解可用模板。"
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_msg},
    ]

    max_rounds = 12
    generated_files: dict[str, str] = {}
    compile_errors: list[dict] | None = None

    for round_idx in range(max_rounds):
        def on_thinking(text: str):
            queue.put_nowait(_make_queue_event("thinking_chunk", "code", {"text": text}))

        try:
            response = await _llm_generate_with_tools_streaming(
                messages=messages,
                tools=registry.get_schema(),
                model="glm-5.2",
                on_thinking=on_thinking,
            )
        except Exception as e:
            logger.error("executor_llm_error", task_id=task_id, error=str(e))
            break

        if response.get("tool_calls"):
            for tc in response["tool_calls"]:
                tool_name = tc["function"]["name"]
                try:
                    tool_args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    tool_args = {}

                queue.put_nowait(_make_queue_event("tool_call", "code", {
                    "tool": tool_name,
                    "args": tool_args,
                    "task_id": task_id,
                }))

                result = await registry.invoke(tool_name, tool_args)

                queue.put_nowait(_make_queue_event("tool_result", "code", {
                    "tool": tool_name,
                    "ok": result.ok,
                    "detail": result.data,
                    "task_id": task_id,
                }))

                if tool_name in ("create_file", "write_code") and result.ok:
                    path = tool_args.get("path", "")
                    content = tool_args.get("content", "")
                    if tool_name == "write_code" and content:
                        generated_files[path] = content
                        queue.put_nowait(_make_queue_event("file_start", "code", {"path": path}))
                        chunk_size = 200
                        for i in range(0, len(content), chunk_size):
                            queue.put_nowait(_make_queue_event("file_chunk", "code", {
                                "path": path,
                                "content": content[i:i + chunk_size],
                                "chunk_index": i // chunk_size,
                                "is_last_chunk_for_file": (i + chunk_size >= len(content)),
                            }))
                        queue.put_nowait(_make_queue_event("file_complete", "code", {"path": path}))

                elif tool_name == "use_skill" and result.ok:
                    for f in result.data.get("files", []):
                        fpath = f["path"]
                        fcontent = f["content"]
                        import os as _os
                        _os.makedirs(_os.path.dirname(_os.path.join(project_root, fpath)), exist_ok=True)
                        with open(_os.path.join(project_root, fpath), "w", encoding="utf-8") as wf:
                            wf.write(fcontent)
                        if fpath not in generated_files:
                            generated_files[fpath] = fcontent

                elif tool_name == "compile_project":
                    errors = result.data.get("errors", []) if not result.ok else []
                    compile_errors = errors if not result.ok else None
                    queue.put_nowait(_make_queue_event("compile_status", "code", {
                        "ok": result.ok,
                        "errors": errors,
                        "task_id": task_id,
                    }))

                messages.append({"role": "assistant", "content": None, "tool_calls": [tc]})
                messages.append({"role": "tool", "tool_call_id": tc["id"],
                    "content": json.dumps({"ok": result.ok, "data": result.data, "error": result.error},
                    ensure_ascii=False)})

        elif response.get("content"):
            content = response["content"]
            messages.append({"role": "assistant", "content": content})
            if "__TASK_DONE__" in content:
                break

        # Auto-compile every 4 rounds
        if round_idx > 0 and round_idx % 4 == 0 and generated_files:
            compile_result = await registry.invoke("compile_project", {})
            ok = compile_result.ok
            errors = compile_result.data.get("errors", []) if not ok else []
            queue.put_nowait(_make_queue_event("compile_status", "code", {
                "ok": ok, "errors": errors, "task_id": task_id,
            }))
            if ok and not errors:
                break

    # Build summary
    summary = f"Task {task_id} done: {len(generated_files)} files"
    compile_err_count = len(compile_errors) if compile_errors else 0

    queue.put_nowait(_make_queue_event("task_complete", "code", {
        "task_id": task_id,
        "summary": summary,
        "file_count": len(generated_files),
        "compile_errors": compile_err_count,
    }))

    return {
        "task_id": task_id,
        "status": "done" if not compile_errors else "failed",
        "generated_files": generated_files,
        "compile_errors": compile_errors,
        "summary": summary,
    }
```

- [ ] **Step 5: 新增 planner_reflect_node 函数**

在 `executor_task` 之后插入：

```python
async def planner_reflect_node(
    state: GenerationState,
    queue,
) -> GenerationState:
    """
    Planner REFLECT — 收集所有 Executor 结果，决定下一步。
    Returns updated state with decision baked in.
    """
    logger.info("planner_reflect_start")

    dag = state.get("planner_dag", {})
    context_summary = state.get("context_summary", {})
    generated_files = state.get("generated_files", {})
    compile_errors = state.get("compile_errors")

    # Update context_summary with latest file contracts
    key_exports = context_summary.get("key_exports", {})
    for path, content in generated_files.items():
        key_exports[path] = extract_interface_contract(path, content)
    context_summary["key_exports"] = key_exports

    # Check if all tasks are done
    all_done = all(
        t.get("status") in ("done", "failed")
        for t in dag.get("tasks", [])
    )
    failed_tasks = [
        t for t in dag.get("tasks", [])
        if t.get("status") == "failed"
    ]

    if all_done and not failed_tasks and not compile_errors:
        # All good
        queue.put_nowait(_make_queue_event("planner_reflect", "code", {
            "decision": "done",
            "reason": "所有任务完成，编译通过",
        }))
        state["context_summary"] = context_summary
        state["stage_phase"] = "complete"
        return state

    if all_done and failed_tasks:
        # Some tasks failed — reflect on what to do
        feedback = f"失败任务: {json.dumps(failed_tasks, ensure_ascii=False)}"
        queue.put_nowait(_make_queue_event("planner_reflect", "code", {
            "decision": "has_failures",
            "failed_task_ids": [t["id"] for t in failed_tasks],
        }))

        # Auto-retry failed tasks once
        for t in dag.get("tasks", []):
            if t.get("status") == "failed":
                t["status"] = "pending"
                t["compile_errors"] = None

        state["planner_reflect_count"] = state.get("planner_reflect_count", 0) + 1
        state["context_summary"] = context_summary
        return state

    state["context_summary"] = context_summary
    return state
```

- [ ] **Step 6: 验证**

```bash
cd ai-design-platform-server/ai-service
python -c "
from app.services.generation.nodes import planner_node, executor_task, planner_reflect_node, EXECUTOR_SYSTEM_PROMPT
print('OK — new node functions importable')
"
```

---

### Task 6: 改造 graph.py Phase 3 — Planner + Executor 流

**Files:**
- Modify: `ai-design-platform-server/ai-service/app/services/generation/graph.py`

- [ ] **Step 1: 更新 imports**

在文件顶部的 imports 中将 `code_node` 替换为新的 functions：

```python
from .nodes import (
    analysis_node,
    design_node,
    code_node,
    review_node,
    e2e_node,
    planner_node,
    executor_task,
    planner_reflect_node,
)
```

- [ ] **Step 2: 替换 Phase 3 代码生成段**

将 `# ── Phase 3: Code generation (streaming via event queue) ──` 整个代码块（从 line 243 到 line 277）替换为：

```python
        # ── Phase 3: Planner + Executor ReAct (streaming) ──
        if not state.get("generated_files"):
            import asyncio as _asyncio
            from .tools.registry import ToolRegistry
            import tempfile, os as _os, json as _json, re

            _raw_name = state.get("requirement", "project")[:30]
            _safe_name = re.sub(r'[^\w]', '_', _raw_name)[:30].strip('_') or "ai-gen-project"
            project_root = _os.path.join(tempfile.gettempdir(), "ai-gen", _safe_name)

            registry = ToolRegistry(project_root)

            yield self._make_event("stage_start", "code", {"phase": "planning"})

            event_queue: _asyncio.Queue = _asyncio.Queue()

            # ── Step 1: Planner → Task DAG ──
            gen_task = _asyncio.create_task(planner_node(state, event_queue))

            while not gen_task.done() or not event_queue.empty():
                try:
                    evt = await _asyncio.wait_for(event_queue.get(), timeout=0.1)
                    yield evt
                except _asyncio.TimeoutError:
                    pass

            state = gen_task.result()
            dag = state.get("planner_dag", {})
            tasks = dag.get("tasks", [])

            if not tasks:
                yield self._make_event("error", "code", {"reason": "Planner produced no tasks"})
                return

            generated_files: dict[str, str] = {}
            all_compile_errors: list[dict] | None = None
            max_planner_rounds = 3

            for planner_round in range(max_planner_rounds):
                # ── Step 2: Execute each pending task ──
                pending = [t for t in tasks if t.get("status") in ("pending", None)]

                for task in pending:
                    # Check deps satisfied
                    deps_ok = all(
                        any(
                            dt["id"] == dep_id and dt.get("status") == "done"
                            for dt in tasks
                        )
                        for dep_id in task.get("deps", [])
                    )
                    if not deps_ok:
                        continue  # Skip — dependencies not yet done

                    task["status"] = "running"

                    # Build executor context
                    registry.set_generated_files(generated_files)
                    state["generated_files"] = generated_files

                    exec_queue: _asyncio.Queue = _asyncio.Queue()
                    exec_gen_task = _asyncio.create_task(
                        executor_task(state, task, exec_queue, project_root, registry)
                    )

                    while not exec_gen_task.done() or not exec_queue.empty():
                        try:
                            evt = await _asyncio.wait_for(exec_queue.get(), timeout=0.1)
                            yield evt
                        except _asyncio.TimeoutError:
                            pass

                    result = exec_gen_task.result()
                    task["status"] = result["status"]
                    task["executor_summary"] = result["summary"]
                    task["compile_errors"] = result["compile_errors"]

                    # Merge generated files
                    for path, content in result.get("generated_files", {}).items():
                        generated_files[path] = content
                        # Also write to disk
                        full_path = _os.path.join(project_root, path)
                        _os.makedirs(_os.path.dirname(full_path), exist_ok=True)
                        with open(full_path, "w", encoding="utf-8") as wf:
                            wf.write(content)

                    if result.get("compile_errors"):
                        all_compile_errors = result["compile_errors"]

                    # Update state for context management
                    dag["completed_tasks"] = sum(
                        1 for t in tasks if t.get("status") in ("done", "failed")
                    )
                    state["planner_dag"] = dag
                    state["generated_files"] = generated_files
                    state["context_summary"] = state.get("context_summary", {"key_exports": {}, "completed_tasks": []})

                # ── Step 3: Planner REFLECT ──
                state["generated_files"] = generated_files
                reflect_queue: _asyncio.Queue = _asyncio.Queue()
                reflect_task = _asyncio.create_task(planner_reflect_node(state, reflect_queue))

                while not reflect_task.done() or not reflect_queue.empty():
                    try:
                        evt = await _asyncio.wait_for(reflect_queue.get(), timeout=0.1)
                        yield evt
                    except _asyncio.TimeoutError:
                        pass

                state = reflect_task.result()

                # Check exit conditions
                if state.get("stage_phase") == "complete":
                    break  # All done, all passed

                # If still pending tasks, loop back
                still_pending = any(
                    t.get("status") in ("pending", "running", None)
                    for t in state.get("planner_dag", {}).get("tasks", [])
                )
                if not still_pending:
                    break  # All tasks processed (some may have failed)

            # Final compilation check
            compile_result = await registry.invoke("compile_project", {})
            compile_ok = compile_result.ok
            errors = compile_result.data.get("errors", []) if not compile_ok else []
            all_compile_errors = errors if not compile_ok else None

            yield self._make_event("compile_status", "code", {
                "ok": compile_ok,
                "errors": errors,
            })

            state["generated_files"] = generated_files
            state["compile_errors"] = all_compile_errors
            state["code_result"] = _json.dumps(generated_files, ensure_ascii=False)
            state["stage_phase"] = "complete"

            yield self._make_event("code_gen_done", "code", {
                "total_files": len(generated_files),
                "compile_errors": len(all_compile_errors) if all_compile_errors else 0,
                "app_name": _safe_name,
                "app_port": 8100 + (hash(_safe_name) % 100),
            })

            yield self._make_event("stage_complete", "code", {
                "summary": f"Generated {len(generated_files)} files in {len(tasks)} tasks",
            })
            yield self._make_event("human_confirm_required", "code", {
                "message": "Please review the code output.",
            })
            return
```

- [ ] **Step 3: 验证**

```bash
cd ai-design-platform-server/ai-service
python -c "
from app.services.generation.graph import GraphRunner
runner = GraphRunner()
print('OK — GraphRunner imports with new planner/executor flow')
"
```

---

## Phase 2: 前端 — Planner/Executor 事件 + AgentLog task 分组

### Task 7: 扩展类型定义

**Files:**
- Modify: `ai-design-platform-web/packages/ai-generation-app/src/types/generation.ts`

- [ ] **Step 1: 新增类型**

在文件末尾追加：

```typescript
// ── Planner/Executor Types ──

export interface PlannerTaskDef {
  id: string
  type: 'bootstrap' | 'business'
  description: string
  deps: string[]
  files: string[]
  contract: Record<string, any>
  status: 'pending' | 'running' | 'done' | 'failed'
  executorSummary?: string
  compileErrors?: CompileErrorEntry[]
}

export interface TaskGroup {
  taskId: string
  description: string
  files: string[]
  status: 'pending' | 'running' | 'done' | 'failed'
  entries: AgentLogEntry[]
  fileCount: number
  compileErrors: number
}

// Extend AgentLogEntry for task-level events
export type AgentLogEntryType =
  | AgentLogEntry['type']
  | 'task_group_header'
  | 'planner_dag'
  | 'planner_reflect'

// HMR Event types from iframe
export interface HmrEvent {
  type: 'hot-replace' | 'hot-rerender' | 'warm-reload' | 'full-reload'
  file: string
  timestamp: number
}
```

- [ ] **Step 2: 扩展 GraphEventTypeExtended**

在 `GraphEventTypeExtended` 联合类型末尾追加新事件类型：

```typescript
  | 'planner_start' | 'planner_dag' | 'planner_reflect'
  | 'task_start' | 'task_complete' | 'task_failed'
  | 'context_summarized' | 'contract_verify'
```

- [ ] **Step 3: 验证**

```bash
cd ai-design-platform-web
npx vue-tsc --noEmit --project packages/ai-generation-app/tsconfig.json 2>&1 | head -20
```

---

### Task 8: 扩展 generation store

**Files:**
- Modify: `ai-design-platform-web/packages/ai-generation-app/src/stores/generation.ts`

- [ ] **Step 1: 新增 import**

在现有 imports 后追加：

```typescript
import type { PlannerTaskDef, TaskGroup } from '@/types/generation'
```

- [ ] **Step 2: 新增 state 字段**

在 `agentLogEntries` 之后追加：

```typescript
  const plannerTasks = ref<PlannerTaskDef[]>([])
  const taskGroups = ref<Map<string, TaskGroup>>(new Map())
  const currentTaskId = ref<string | null>(null)
  const plannerReasoning = ref<string>('')
```

- [ ] **Step 3: 新增 actions**

在 `updateLastAgentLogEntry` 之后追加：

```typescript
  function setPlannerTasks(tasks: PlannerTaskDef[]): void {
    plannerTasks.value = tasks
    taskGroups.value = new Map()
    for (const t of tasks) {
      taskGroups.value.set(t.id, {
        taskId: t.id,
        description: t.description,
        files: t.files,
        status: t.status,
        entries: [],
        fileCount: 0,
        compileErrors: 0,
      })
    }
  }

  function setCurrentTask(taskId: string | null): void {
    currentTaskId.value = taskId
  }

  function addTaskLogEntry(taskId: string, entry: AgentLogEntry): void {
    const group = taskGroups.value.get(taskId)
    if (group) {
      group.entries.push(entry)
      if (entry.type === 'file_complete') group.fileCount++
      if (entry.type === 'compile' && !entry.compileOk) {
        group.compileErrors = (entry.compileErrors || []).length
      }
    }
  }

  function updateTaskStatus(taskId: string, status: PlannerTaskDef['status']): void {
    const task = plannerTasks.value.find(t => t.id === taskId)
    if (task) task.status = status
    const group = taskGroups.value.get(taskId)
    if (group) group.status = status
  }

  function setPlannerReasoning(text: string): void {
    plannerReasoning.value = text
  }
```

- [ ] **Step 4: 更新 resetAll**

在 `resetAll` 中添加：

```typescript
    plannerTasks.value = []
    taskGroups.value = new Map()
    currentTaskId.value = null
    plannerReasoning.value = ''
```

- [ ] **Step 5: 更新 return block**

在 return 中添加导出：

```typescript
    plannerTasks, taskGroups, currentTaskId, plannerReasoning,
    setPlannerTasks, setCurrentTask, addTaskLogEntry, updateTaskStatus, setPlannerReasoning,
```

- [ ] **Step 6: 验证**

```bash
cd ai-design-platform-web
npx vue-tsc --noEmit --project packages/ai-generation-app/tsconfig.json 2>&1 | head -20
```

---

### Task 9: 扩展 AgentLog.vue — task 分组展示

**Files:**
- Modify: `ai-design-platform-web/packages/ai-generation-app/src/components/AgentLog.vue`

- [ ] **Step 1: 更新 script — 新增 props、task 分组渲染**

将 `<script setup>` 替换为：

```typescript
<script setup lang="ts">
import { watch, ref, nextTick, computed } from 'vue'
import { useGenerationStore } from '@/stores/generation'
import type { AgentLogEntry, PlannerTaskDef, TaskGroup } from '@/types/generation'

const props = defineProps<{
  entries: AgentLogEntry[]
  isStreaming: boolean
}>()

const emit = defineEmits<{
  'entry-click': [entry: AgentLogEntry]
}>()

const store = useGenerationStore()
const containerRef = ref<HTMLElement | null>(null)
const collapsedTasks = ref<Set<string>>(new Set())

const hasTaskGroups = computed(() => store.taskGroups.size > 0)

function scrollToBottom(): void {
  nextTick(() => {
    if (containerRef.value) {
      containerRef.value.scrollTop = containerRef.value.scrollHeight
    }
  })
}

watch(() => props.entries.length, scrollToBottom)
watch(() => store.taskGroups, scrollToBottom, { deep: true })

function toggleTask(taskId: string): void {
  if (collapsedTasks.value.has(taskId)) {
    collapsedTasks.value.delete(taskId)
  } else {
    collapsedTasks.value.add(taskId)
  }
  collapsedTasks.value = new Set(collapsedTasks.value)
}

function toolIcon(status?: string): string {
  if (status === 'running') return '\u{1F504}'
  if (status === 'done') return '✅'
  if (status === 'error') return '❌'
  return '\u{1F527}'
}

function formatToolName(name?: string): string {
  const map: Record<string, string> = {
    create_file: '创建文件', write_code: '写入代码', compile_project: '编译检查',
    fix_error: '修复错误', use_skill: 'Skill 模板', mcp_query: 'MCP 查询',
    list_skills: '列出模板', get_compile_errors: '获取错误', delete_file: '删除文件',
    summarize_context: '压缩上下文', retrieve_context: '检索上下文', verify_contract: '契约校验',
  }
  return name ? (map[name] || name) : ''
}

function handleEntryClick(entry: AgentLogEntry): void {
  emit('entry-click', entry)
}

function taskStatusIcon(status: string): string {
  return status === 'done' ? '✅' : status === 'running' ? '\u{1F504}' : status === 'failed' ? '❌' : '⏳'
}

function taskTypeLabel(type: string): string {
  return type === 'bootstrap' ? '\u{1F527} 脚手架' : '\u{1F4BB} 业务'
}
</script>
```

- [ ] **Step 2: 更新 template — 增加 task 分组渲染**

在 `<template>` 的 `<div class="space-y-1.5">` 最前面插入 task 分组视图：

```html
      <!-- Planner 推理文字 -->
      <div v-if="store.plannerReasoning" class="text-xs p-2 bg-purple-50 border border-purple-200 rounded text-purple-700 mb-2">
        <div class="font-medium mb-0.5">\u{1F9E0} Planner 分析</div>
        <div class="whitespace-pre-wrap text-[11px]">{{ store.plannerReasoning }}</div>
      </div>

      <!-- Task 分组视图 -->
      <template v-if="hasTaskGroups">
        <div
          v-for="task in store.plannerTasks"
          :key="task.id"
          class="border rounded overflow-hidden"
          :class="{
            'border-green-300': task.status === 'done',
            'border-blue-300': task.status === 'running',
            'border-red-300': task.status === 'failed',
            'border-gray-200': task.status === 'pending',
          }"
        >
          <!-- Task Header -->
          <div
            class="flex items-center gap-2 px-2 py-1.5 cursor-pointer hover:bg-gray-100 text-xs"
            :class="{
              'bg-green-50': task.status === 'done',
              'bg-blue-50': task.status === 'running',
              'bg-red-50': task.status === 'failed',
              'bg-gray-50': task.status === 'pending',
            }"
            @click="toggleTask(task.id)"
          >
            <span>{{ collapsedTasks.has(task.id) ? '▶' : '▼' }}</span>
            <span>{{ taskStatusIcon(task.status) }}</span>
            <span class="text-gray-400 text-[10px]">{{ taskTypeLabel(task.type) }}</span>
            <span class="font-medium truncate flex-1">{{ task.description }}</span>
            <span class="text-gray-400 text-[10px]">{{ task.files.length }} files</span>
          </div>

          <!-- Task Entries (collapsible) -->
          <div v-if="!collapsedTasks.has(task.id)" class="border-t border-gray-100">
            <template v-for="entry in store.taskGroups.get(task.id)?.entries || []" :key="entry.id">
              <!-- Thinking -->
              <div v-if="entry.type === 'thinking'" class="text-xs px-2 py-0.5">
                <div class="flex items-center gap-1 text-gray-400 mb-0.5">
                  <span>\u{1F4AD}</span>
                  <span v-if="!entry.thinkingDone" class="text-blue-400 animate-pulse">...</span>
                </div>
                <div class="p-1.5 bg-white rounded border border-gray-100 text-gray-600 whitespace-pre-wrap max-h-[120px] overflow-y-auto text-[10px] leading-relaxed">
                  {{ entry.thinkingText?.slice(-300) }}
                </div>
              </div>

              <!-- Tool Call -->
              <div
                v-else-if="entry.type === 'tool_call'"
                class="flex items-center gap-1.5 px-2 py-0.5 text-[10px] cursor-pointer hover:bg-gray-50 border-b border-gray-50"
                :class="{
                  'text-blue-600': entry.toolStatus === 'running',
                  'text-green-600': entry.toolStatus === 'done',
                  'text-red-600': entry.toolStatus === 'error',
                }"
                @click="handleEntryClick(entry)"
              >
                <span>{{ toolIcon(entry.toolStatus) }}</span>
                <span class="font-mono">{{ formatToolName(entry.toolName) }}</span>
                <span v-if="entry.toolArgs?.path" class="text-gray-400 truncate">→ {{ entry.toolArgs.path }}</span>
              </div>

              <!-- File Start -->
              <div
                v-else-if="entry.type === 'file_start'"
                class="flex items-center gap-1.5 px-2 py-0.5 text-[10px] cursor-pointer hover:bg-gray-50"
                :class="{ 'text-blue-600': !entry.fileDone, 'text-green-600': entry.fileDone }"
                @click="handleEntryClick(entry)"
              >
                <span>\u{1F4C4}</span>
                <span class="font-mono">{{ entry.filePath }}</span>
                <span v-if="entry.fileDone" class="text-green-500 ml-auto">✅</span>
                <span v-else class="text-blue-400 animate-pulse ml-auto text-[9px]">生成中...</span>
              </div>

              <!-- Compile -->
              <div
                v-else-if="entry.type === 'compile'"
                class="px-2 py-0.5 text-[10px] border-b border-gray-50"
                :class="entry.compileOk ? 'text-green-600' : 'text-red-600'"
              >
                ⚡ 编译{{ entry.compileOk ? '✅' : '❌ ' + (entry.compileErrors?.length || 0) + ' errors' }}
              </div>
            </template>
            <div v-if="(store.taskGroups.get(task.id)?.entries.length || 0) === 0 && task.status === 'pending'" class="text-center text-gray-400 text-[10px] py-2">
              等待执行...
            </div>
          </div>
        </div>
      </template>

      <!-- Fallback: 无 task 分组时直接用 entries 渲染 (兼容旧模式) -->
      <template v-if="!hasTaskGroups">
```

然后将原有的 entry 渲染部分包裹在 `<template v-if="!hasTaskGroups">` 中，并在最后关闭 `</template>`。

- [ ] **Step 3: 验证**

```bash
cd ai-design-platform-web
npx vue-tsc --noEmit --project packages/ai-generation-app/tsconfig.json 2>&1 | grep -v "PRDGeneratorView" | grep -v "public-path" | grep -v "main.ts" | head -20
```

---

### Task 10: 扩展 useCodeStream.ts — 新增 planner/task 事件处理

**Files:**
- Modify: `ai-design-platform-web/packages/ai-generation-app/src/composables/useCodeStream.ts`

- [ ] **Step 1: 新增事件 case**

在 `handleCodeSSEEvent` 的 switch 中新增以下 cases：

```typescript
    case 'planner_start':
      s.agentLogEntries.push({
        id: entryId(), type: 'phase_summary', timestamp: Date.now(),
        summary: event.message || 'Planner 正在分析设计方案...',
      })
      break

    case 'planner_dag': {
      const tasks: PlannerTaskDef[] = (event.tasks || []).map((t: any) => ({
        ...t,
        status: t.status || 'pending',
      }))
      s.setPlannerTasks(tasks)
      s.setPlannerReasoning(event.reasoning || '')
      s.agentLogEntries.push({
        id: entryId(), type: 'phase_summary', timestamp: Date.now(),
        summary: `任务拆解完成：${tasks.length} 个任务`,
        fileTotal: tasks.length,
      })
      break
    }

    case 'planner_reflect':
      s.agentLogEntries.push({
        id: entryId(), type: 'phase_summary', timestamp: Date.now(),
        summary: `Planner 决策: ${event.decision} — ${event.reason || ''}`,
      })
      break

    case 'task_start':
      s.setCurrentTask(event.task_id)
      s.updateTaskStatus(event.task_id, 'running')
      break

    case 'task_complete':
      s.updateTaskStatus(event.task_id, event.compile_errors === 0 ? 'done' : 'failed')
      break

    case 'task_failed':
      s.updateTaskStatus(event.task_id, 'failed')
      break
```

- [ ] **Step 2: 修改 tool_call / tool_result / file_start / file_complete / compile_status 事件**

将这些事件 handler 中创建 entry 的代码改为同时添加到 task group：

在 `tool_call` case 中，在 `s.agentLogEntries.push(...)` 之后添加：

```typescript
      if (event.task_id) {
        const entry = s.agentLogEntries.at(-1)
        if (entry) s.addTaskLogEntry(event.task_id, entry)
      }
```

对 `file_start`, `compile_status` 同样处理。

- [ ] **Step 3: 在文件顶部新增 import**

```typescript
import type { PlannerTaskDef } from '@/types/generation'
```

- [ ] **Step 4: 验证**

```bash
cd ai-design-platform-web
npx vue-tsc --noEmit --project packages/ai-generation-app/tsconfig.json 2>&1 | grep "useCodeStream" | head -10
```

---

## Phase 3: 微应用工程模板

### Task 11: 创建 qiankun-app Skill 模板

**Files:**
- Create: `ai-design-platform-server/ai-service/app/services/generation/skills/qiankun-app.json`

- [ ] **Step 1: 写入 Skill 定义**

```json
{
  "name": "qiankun-app",
  "description": "qiankun 微应用生命周期入口模板，生成 main.ts + public-path.ts + webpack 配置",
  "parameters": {
    "appName": {
      "type": "string",
      "description": "微应用名称，用于 webpack output.library.name 和 qiankun 注册"
    },
    "routerMode": {
      "type": "string",
      "description": "路由模式: hash | history",
      "default": "hash"
    }
  },
  "produces": [
    {
      "path": "src/main.ts",
      "template": "import './public-path'\nimport { createApp, type App as VueApp } from 'vue'\nimport { createPinia } from 'pinia'\nimport App from './App.vue'\nimport router from './router'\n\nlet app: VueApp | null = null\n\nfunction render(props: { container?: HTMLElement } = {}) {\n  const container = props.container\n  const instance = createApp(App)\n  instance.use(createPinia())\n  instance.use(router)\n  const mountPoint = container\n    ? container.querySelector('#app') || container\n    : document.getElementById('app') || document.body\n  instance.mount(mountPoint as HTMLElement)\n  app = instance\n}\n\nif (!(window as any).__POWERED_BY_QIANKUN__) {\n  render()\n}\n\nexport async function bootstrap(): Promise<void> {\n  // qiankun lifecycle — no-op\n}\n\nexport async function mount(props: any): Promise<void> {\n  render(props)\n}\n\nexport async function unmount(): Promise<void> {\n  if (app) {\n    app.unmount()\n    app = null\n  }\n}\n"
    },
    {
      "path": "src/public-path.ts",
      "template": "if ((window as any).__POWERED_BY_QIANKUN__) {\n  // eslint-disable-next-line\n  // @ts-ignore\n  __webpack_public_path__ = (window as any).__INJECTED_PUBLIC_PATH_BY_QIANKUN__\n}\n"
    },
    {
      "path": "webpack/webpack.common.js",
      "template": "const path = require('path')\nconst { VueLoaderPlugin } = require('vue-loader')\nconst HtmlWebpackPlugin = require('html-webpack-plugin')\n\nmodule.exports = {\n  entry: './src/main.ts',\n  output: {\n    path: path.resolve(__dirname, '../dist'),\n    filename: 'js/[name].[contenthash:8].js',\n    chunkFilename: 'js/[name].[contenthash:8].chunk.js',\n    library: {\n      name: '{{appName}}',\n      type: 'umd',\n    },\n    clean: true,\n  },\n  resolve: {\n    extensions: ['.ts', '.tsx', '.js', '.vue', '.json'],\n    alias: { '@': path.resolve(__dirname, '../src') },\n  },\n  module: {\n    rules: [\n      { test: /\\.vue$/, loader: 'vue-loader' },\n      { test: /\\.tsx?$/, loader: 'ts-loader', exclude: /node_modules/,\n        options: { appendTsSuffixTo: [/\\.vue$/], transpileOnly: true } },\n      { test: /\\.css$/, use: ['style-loader', 'css-loader'] },\n      { test: /\\.(png|jpe?g|gif|svg)$/, type: 'asset/resource' },\n    ],\n  },\n  plugins: [\n    new VueLoaderPlugin(),\n    new HtmlWebpackPlugin({\n      template: './index.html',\n      filename: 'index.html',\n    }),\n  ],\n  devServer: {\n    port: 8100,\n    headers: { 'Access-Control-Allow-Origin': '*' },\n    historyApiFallback: true,\n  },\n}\n"
    }
  ],
  "contract": {
    "exports": ["bootstrap", "mount", "unmount"]
  }
}
```

- [ ] **Step 2: 更新 skill_loader.py 以支持 contract 字段**

在 `apply` 方法的返回中添加 contract：

```python
        return ToolResult(ok=True, data={
            "skill": name,
            "files": files,
            "contract": skill.get("contract", {}),
        })
```

- [ ] **Step 3: 验证**

```bash
cd ai-design-platform-server/ai-service
python -c "
from app.services.generation.tools.skill_loader import SkillLoader
import asyncio
sl = SkillLoader()
result = asyncio.run(sl.apply('qiankun-app', {'appName': 'test-app'}))
assert result.ok, f'Failed: {result.error}'
assert len(result.data['files']) == 3
print('OK — qiankun-app skill works, files:', [f['path'] for f in result.data['files']])
"
```

---

## Phase 4: iframe 增量编译 + HMR

### Task 12: 创建 HMR Runtime 脚本

**Files:**
- Create: `ai-design-platform-web/packages/ai-generation-app/src/utils/hmrRuntime.ts`

- [ ] **Step 1: 写入 iframe 内 HMR runtime**

```typescript
// hmrRuntime.ts — 注入到 PreviewFrame iframe 中的 HMR runtime
// 此文件编译为字符串，通过 srcdoc 注入到 iframe

export function generateHmrRuntimeScript(): string {
  return `
<script>
(function() {
  'use strict';

  // ── ModuleRegistry ──
  const modules = new Map();   // path -> { compiled, deps[], hot }

  function registerModule(path, compiled, deps) {
    modules.set(path, { compiled, deps: deps || [], hot: true });
  }

  function getModule(path) {
    return modules.get(path);
  }

  function getDependents(path) {
    const result = [];
    for (const [p, m] of modules) {
      if (m.deps.includes(path)) result.push(p);
    }
    return result;
  }

  // ── HotReloader ──
  function hotReplace(path, newCompiled) {
    const old = modules.get(path);
    if (!old) {
      // New module — just register
      registerModule(path, newCompiled, []);
      return { type: 'hot-replace', file: path };
    }

    // Update module
    modules.set(path, { ...old, compiled: newCompiled, hot: true });

    // Notify parent
    const dependents = getDependents(path);
    if (dependents.length > 0) {
      // Re-render dependents
      for (const dep of dependents) {
        const m = modules.get(dep);
        if (m && m.compiled && typeof m.compiled.rerender === 'function') {
          try {
            m.compiled.rerender();
          } catch(e) {
            console.warn('[HMR] rerender failed for', dep, e);
          }
        }
      }
    }

    return { type: 'hot-replace', file: path, dependents };
  }

  function warmReload(path, newCompiled) {
    registerModule(path, newCompiled, []);
    // Trigger full re-render of dependents
    const dependents = getDependents(path);
    for (const dep of dependents) {
      const m = modules.get(dep);
      if (m && m.compiled && typeof m.compiled.rerender === 'function') {
        try { m.compiled.rerender(); } catch(e) {}
      }
    }
    return { type: 'warm-reload', file: path, dependents };
  }

  // ── IncrementalCompiler (simplified — registers pre-compiled code from parent) ──
  function onFileUpdate(path, code, isLastChunk) {
    // In this architecture, the parent compiles Vue SFC and sends compiled JS
    // The iframe just registers and hot-replaces
    try {
      // Execute compiled code to get component definition
      const exports = {};
      const fn = new Function('exports', 'require', code);
      fn(exports, function fakeRequire(p) { return modules.get(p)?.compiled; });
      const compiled = exports.default || exports;

      if (isLastChunk) {
        const old = modules.get(path);
        if (old) {
          return hotReplace(path, compiled);
        } else {
          registerModule(path, compiled, []);
          return { type: 'full-reload', file: path };
        }
      }
      return { type: 'chunk-accumulated', file: path };
    } catch(e) {
      if (e instanceof SyntaxError) {
        return { type: 'compile-error', file: path, error: e.message, recoverable: true };
      }
      return { type: 'compile-error', file: path, error: e.message, recoverable: false };
    }
  }

  // ── Message handlers ──
  window.addEventListener('message', function(e) {
    if (!e.data || !e.data.type) return;

    switch(e.data.type) {
      case 'hmr-file-chunk':
        const result = onFileUpdate(e.data.path, e.data.code, e.data.isLast);
        window.parent.postMessage({ type: 'hmr-result', ...result }, '*');
        break;

      case 'hmr-css-update':
        // Hot replace CSS
        let styleEl = document.getElementById('hmr-style-' + e.data.path.replace(/[^a-z0-9]/gi, '-'));
        if (!styleEl) {
          styleEl = document.createElement('style');
          styleEl.id = 'hmr-style-' + e.data.path.replace(/[^a-z0-9]/gi, '-');
          document.head.appendChild(styleEl);
        }
        styleEl.textContent = e.data.css;
        window.parent.postMessage({ type: 'hmr-result', type2: 'hot-replace', file: e.data.path, css: true }, '*');
        break;

      case 'hmr-full-reload':
        window.location.reload();
        break;
    }
  });

  // Signal ready
  window.parent.postMessage({ type: 'hmr-ready' }, '*');
})();
<\/script>`;
}
```

- [ ] **Step 2: 验证**

```bash
cd ai-design-platform-web
npx vue-tsc --noEmit --project packages/ai-generation-app/tsconfig.json 2>&1 | grep "hmrRuntime" | head -10
```

---

### Task 13: 改造 PreviewFrame.vue — 集成 HMR

**Files:**
- Modify: `ai-design-platform-web/packages/ai-generation-app/src/components/PreviewFrame.vue`

- [ ] **Step 1: 注入 HMR runtime 到 iframe srcdoc**

```typescript
<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted } from 'vue'
import { useGenerationStore } from '@/stores/generation'
import { useMultiCompiler } from '@/composables/useMultiCompiler'
import { generateHmrRuntimeScript } from '@/utils/hmrRuntime'
import { buildPreviewHtml } from '@/utils/buildPreviewHtml'
import { useComponentDocs } from './useComponentDocs'

const store = useGenerationStore()
const { getConfig } = useComponentDocs()
const { isCompiling, compileNow } = useMultiCompiler()
const iframeRef = ref<HTMLIFrameElement | null>(null)
const iframeReady = ref(false)
const hmrReady = ref(false)
const errorMessage = ref<string | null>(null)

const hmrRuntime = generateHmrRuntimeScript()

function buildHmrPreviewHtml(): string {
  const cdnUrls = getConfig().cdnUrls
  const cdnTags = cdnUrls.map((url: string) => {
    if (url.endsWith('.css')) return `<link rel="stylesheet" href="${url}">`
    return `<script src="${url}"><\/script>`
  }).join('\n')

  return `<!DOCTYPE html>
<html><head><meta charset="utf-8">
${cdnTags}
<style>body { margin: 0; padding: 16px; font-family: -apple-system, sans-serif; }</style>
</head><body>
<div id="app"></div>
${hmrRuntime}
</body></html>`
}

function initIframe(): void {
  if (!iframeRef.value) return
  iframeRef.value.srcdoc = buildHmrPreviewHtml()
  iframeReady.value = false
  hmrReady.value = false
}

function sendHmrChunk(path: string, code: string, isLast: boolean): void {
  if (!iframeRef.value?.contentWindow || !hmrReady.value) return
  iframeRef.value.contentWindow.postMessage({
    type: 'hmr-file-chunk',
    path,
    code,
    isLast,
  }, '*')
}

function sendHmrCss(path: string, css: string): void {
  if (!iframeRef.value?.contentWindow || !hmrReady.value) return
  iframeRef.value.contentWindow.postMessage({
    type: 'hmr-css-update',
    path,
    css,
  }, '*')
}

function handleMessage(e: MessageEvent): void {
  if (e.source !== iframeRef.value?.contentWindow) return

  if (e.data?.type === 'ready') {
    iframeReady.value = true
    errorMessage.value = null
  }
  if (e.data?.type === 'hmr-ready') {
    hmrReady.value = true
  }
  if (e.data?.type === 'hmr-result') {
    if (e.data.type2 === 'compile-error') {
      errorMessage.value = `[${e.data.file}] ${e.data.error}`
    } else {
      errorMessage.value = null
    }
  }
  if (e.data?.type === 'err') {
    errorMessage.value = e.data.message as string
  }
}

// Watch generated files for HMR updates
watch(
  () => store.generatedFiles,
  (newFiles, oldFiles) => {
    if (!hmrReady.value) return
    for (const [path, content] of Object.entries(newFiles)) {
      const oldContent = (oldFiles as Record<string, string>)?.[path] || ''
      if (content !== oldContent && content) {
        const isNew = !oldContent
        sendHmrChunk(path, content, true)
      }
    }
  },
  { deep: true },
)

// Watch for specific file_chunk events via store
watch(
  () => store.currentGeneratingFile,
  (path) => {
    if (!path || !hmrReady.value) return
    const content = store.generatedFiles[path] || ''
    if (content) {
      sendHmrChunk(path, content, false)
    }
  },
)

onMounted(() => {
  window.addEventListener('message', handleMessage)
  initIframe()
})

onUnmounted(() => {
  window.removeEventListener('message', handleMessage)
})

function refresh(): void {
  initIframe()
}
</script>
```

- [ ] **Step 2: 更新 template — 增加 HMR 状态指示**

在 status 指示器中新增：

```html
        <span v-if="hmrReady" class="text-xs px-2 py-0.5 rounded-full bg-green-100 text-green-700">
          HMR 就绪
        </span>
```

- [ ] **Step 3: 验证**

```bash
cd ai-design-platform-web
npx vue-tsc --noEmit --project packages/ai-generation-app/tsconfig.json 2>&1 | grep "PreviewFrame" | head -10
```

---

## Phase 5: MCP 真实连接

### Task 14: 升级 MCP Bridge 为真实连接

**Files:**
- Modify: `ai-design-platform-server/ai-service/app/services/generation/tools/mcp_bridge.py`

- [ ] **Step 1: 重写 MCPBridge 为真实 stdio MCP 连接**

```python
"""MCP Bridge — connect to real MCP servers via stdio transport."""

import asyncio
import json
import structlog
from .registry import ToolResult

logger = structlog.get_logger()

MCP_SERVERS = {
    "component-docs": {
        "description": "Component library documentation and API reference",
        "command": "npx",
        "args": ["-y", "@anthropic/mcp-server-tdesign"],
        "enabled": True,
    },
    "design-tokens": {
        "description": "Design tokens (colors, spacing, typography)",
        "command": "node",
        "args": ["./mcp-servers/design-tokens-server.js"],
        "enabled": False,
    },
    "type-registry": {
        "description": "TypeScript type definitions from generated files",
        "enabled": True,
        "internal": True,  # Handled internally, not via external process
    },
}


class MCPBridge:
    """Manages connections to MCP servers."""

    def __init__(self):
        self._servers = MCP_SERVERS
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._type_registry: dict[str, str] = {}

    def set_type_registry(self, files: dict[str, str]) -> None:
        """Update the internal type-registry with generated files."""
        self._type_registry = {}
        for path, content in files.items():
            if path.endswith(".ts") or path.endswith(".vue"):
                self._type_registry[path] = content

    async def query(self, server: str, query: str) -> ToolResult:
        """Query an MCP server. Falls back to stub if server unavailable."""
        if server not in self._servers:
            return ToolResult(
                ok=False,
                error=f"Unknown MCP server: {server}. Available: {list(self._servers.keys())}",
            )

        cfg = self._servers[server]
        if not cfg.get("enabled", True):
            return ToolResult(ok=False, error=f"MCP server '{server}' is not enabled.")

        # Internal type-registry (no external process)
        if cfg.get("internal"):
            return await self._query_type_registry(query)

        # External MCP server via stdio
        try:
            result = await self._query_external_mcp(server, cfg, query)
            return result
        except Exception as e:
            logger.warning("mcp_external_failed", server=server, error=str(e))
            # Fallback: stub response so LLM can continue
            return ToolResult(
                ok=True,
                data={
                    "server": server,
                    "query": query,
                    "note": f"MCP server '{server}' temporarily unavailable ({str(e)[:100]}). Use your knowledge to continue.",
                },
            )

    async def _query_type_registry(self, query: str) -> ToolResult:
        """Search internal type registry."""
        query_lower = query.lower()
        results = []
        for path, content in self._type_registry.items():
            if query_lower in content.lower() or query_lower in path.lower():
                # Extract relevant type definitions
                results.append({
                    "file": path,
                    "matches": self._extract_types(content, query),
                })
        return ToolResult(ok=True, data={
            "server": "type-registry",
            "query": query,
            "results": results if results else None,
            "note": "No matching types found" if not results else f"Found in {len(results)} files",
        })

    def _extract_types(self, content: str, query: str) -> list[str]:
        """Extract type/interface definitions matching query."""
        import re
        query_lower = query.lower()
        # Match interfaces and type aliases
        pattern = re.compile(
            r'(?:export\s+)?(?:interface|type)\s+(\w[\w\d]*)\s*(?:extends\s+[^{]+)?\s*\{([^}]+)\}',
            re.MULTILINE | re.DOTALL,
        )
        matches = []
        for m in pattern.finditer(content):
            name = m.group(1)
            body = m.group(2)
            if query_lower in name.lower() or query_lower in body.lower():
                matches.append(f"{name} {{ {body[:200].strip()} }}")
        return matches[:5]

    async def _query_external_mcp(
        self, server: str, cfg: dict, query: str
    ) -> ToolResult:
        """Connect to an external MCP server via stdio and send a query."""
        if server not in self._processes:
            # Launch MCP server process
            try:
                proc = await asyncio.create_subprocess_exec(
                    cfg["command"],
                    *cfg.get("args", []),
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                self._processes[server] = proc
                logger.info("mcp_process_started", server=server, pid=proc.pid)
            except FileNotFoundError:
                raise RuntimeError(f"MCP command not found: {cfg['command']}")

        proc = self._processes[server]

        # Send MCP JSON-RPC request
        request = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "search",
                "arguments": {"query": query},
            },
        }) + "\n"

        try:
            proc.stdin.write(request.encode())
            await proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            # Process died, restart next time
            del self._processes[server]
            raise RuntimeError(f"MCP process for '{server}' disconnected")

        try:
            raw = await asyncio.wait_for(proc.stdout.readline(), timeout=10)
            response = json.loads(raw.decode())
            return ToolResult(ok=True, data={
                "server": server,
                "query": query,
                "result": response.get("result", response),
            })
        except asyncio.TimeoutError:
            return ToolResult(
                ok=True,
                data={
                    "server": server,
                    "query": query,
                    "note": f"MCP '{server}' query timed out. Use your knowledge.",
                },
            )
```

- [ ] **Step 2: 在 ToolRegistry 中集成 type-registry 更新**

修改 `code_node_streaming` 中（或在 Planner/Executor 循环中）每次文件更新后调用 `registry.set_generated_files(generated_files)`（已在 Task 4 中添加 `set_generated_files` 方法）。

在 `_register_builtins` 中更新 `mcp_query` handler 以支持 `set_type_registry`：

```python
    # In mcp_query handler, update type_registry before query
    handler=lambda **kw: self._mcp_bridge.query(**kw),
```

在 `set_generated_files` 中同步更新 MCP bridge：

```python
    def set_generated_files(self, files: dict[str, str]) -> None:
        """Update the generated files cache for context tools and MCP type-registry."""
        self._generated_files = files
        if hasattr(self, '_mcp_bridge'):
            self._mcp_bridge.set_type_registry(files)
```

- [ ] **Step 3: 验证**

```bash
cd ai-design-platform-server/ai-service
python -c "
from app.services.generation.tools.mcp_bridge import MCPBridge
import asyncio
bridge = MCPBridge()
bridge.set_type_registry({'src/types.ts': 'export interface User { id: number; name: string }'})
result = asyncio.run(bridge.query('type-registry', 'User'))
assert result.ok
print('OK — type-registry query result:', result.data)
"
```

---

### Task 15: 端到端验证

- [ ] **Step 1: 验证后端完整导入链**

```bash
cd ai-design-platform-server/ai-service
python -c "
from app.services.generation.state import GenerationState, PlannerTask, TaskDAG
from app.services.generation.planner import PLANNER_SYSTEM_PROMPT, extract_task_dag
from app.services.generation.context_manager import summarize_context, verify_contract
from app.services.generation.nodes import planner_node, executor_task, planner_reflect_node
from app.services.generation.tools.registry import ToolRegistry
from app.services.generation.tools.mcp_bridge import MCPBridge
from app.services.generation.tools.skill_loader import SkillLoader
from app.services.generation.graph import GraphRunner
print('ALL IMPORTS OK')
"
```

- [ ] **Step 2: 验证前端编译**

```bash
cd ai-design-platform-web
npx vue-tsc --noEmit --project packages/ai-generation-app/tsconfig.json 2>&1 | grep -E "^src" | grep -v "PRDGeneratorView" | grep -v "public-path" | grep -v "main.ts" | head -30
```

Expected: no new type errors beyond pre-existing ones.

- [ ] **Step 3: 启动服务并测试 Planner → Executor 流**

```bash
# Start AI service
cd ai-design-platform-server/ai-service
python -m app.main &
# Wait for startup, then test
curl -s -N -X POST "http://localhost:8080/api/v1/generation/stream" \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"# Design\n## Components\n- Header (props: title, user)\n- HomePage (uses Header, Table)"}],"model":"glm-5.2","mode":"graph","skip_analysis":true,"component_lib":"tailwind"}' \
  2>&1 | timeout 60 head -30
```

Expected: events include `planner_start`, `planner_dag`, `task_start`, `task_complete`, `code_gen_done`.

---

## 实施顺序与依赖

```
Phase 1 (Task 1-6): 后端 Planner + Executor
  Task 1 (state.py) ── 无依赖
  Task 2 (planner.py) ── 依赖 Task 1
  Task 3 (context_manager.py) ── 依赖 Task 1
  Task 4 (registry.py) ── 依赖 Task 3
  Task 5 (nodes.py) ── 依赖 Task 2, Task 3
  Task 6 (graph.py) ── 依赖 Task 5

Phase 2 (Task 7-10): 前端事件 + UI
  Task 7 (types) ── 无依赖
  Task 8 (store) ── 依赖 Task 7
  Task 9 (AgentLog) ── 依赖 Task 7, Task 8
  Task 10 (useCodeStream) ── 依赖 Task 7, Task 8

Phase 3 (Task 11): 微应用模板
  Task 11 ── 无依赖

Phase 4 (Task 12-13): HMR
  Task 12 (hmrRuntime) ── 无依赖
  Task 13 (PreviewFrame) ── 依赖 Task 12

Phase 5 (Task 14): MCP
  Task 14 ── 无依赖

Task 15: 端到端验证 ── 依赖所有
```

Phase 1 和 Phase 2 可以并行开发（后端和前端独立）。Phase 3-5 可插在 Phase 1-2 完成后任意顺序执行。

**总工期估算**: 11-15 天
