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
