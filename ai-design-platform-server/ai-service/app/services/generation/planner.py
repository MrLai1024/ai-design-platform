"""Planner Agent — REASON→ACT(DAG)→OBSERVE→REFLECT loop for task decomposition."""

import json
import structlog

logger = structlog.get_logger()

PLANNER_SYSTEM_PROMPT = """你是一个资深前端工程架构师，负责将架构 Spec 拆解为可独立执行的任务。

## 你的职责
1. 依据 Spec 的 directory_tree 推导任务边界（目录/文件组 → 任务）
2. 依据 Spec 的 data_model 与 api_contracts 推导每个任务的接口契约（exports/props/events）
3. 依据 Spec 的 component_tree 与页面-组件引用推导依赖关系（DAG）
4. 依据 Spec 的 tech_stack 推导脚手架任务（仅当构建配置需要工程入口时）
5. 接收执行反馈后动态调整计划

## 任务类型
- **bootstrap**: 工程脚手架任务（仅当 Spec 的 tech_stack.build 需要时创建：qiankun 生命周期、webpack 配置、package.json 等；不需要则不得凭空添加）
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
- 任务与 Spec 结构一一对应：任务边界来自 directory_tree 的目录/文件组，任务 files 必须落在 Spec 声明的路径内；接口契约从 data_model 实体、api_contracts 名称与 component_tree props 推导；依赖关系符合 component_tree 的 uses 与页面引用
- 禁止使用与 Spec 无关的硬编码任务（如无依据的固定 bootstrap 数量、固定文件数上限）
- 每个 task 是一个可独立执行单元，完成自己的文件、满足自己的契约
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


# Spec sections the Planner consumes (task 5.2) — each maps to a decomposition
# input: directory_tree → 任务边界, data_model/api_contracts → 接口契约,
# component_tree → 依赖, tech_stack → 脚手架推导.
_SPEC_PROMPT_SECTIONS = (
    "tech_stack",
    "directory_tree",
    "data_model",
    "api_contracts",
    "routing",
    "state_management",
    "component_tree",
    "pages",
)


def _spec_prompt_blocks(spec: dict) -> list[str]:
    """Serialize the Spec into the Planner's user prompt (JSON sections)."""
    blocks = ["## 架构 Spec（唯一工程输入，任务拆解必须以此为准）"]
    for key in _SPEC_PROMPT_SECTIONS:
        value = spec.get(key)
        if value is None:
            continue
        blocks.append(f"### {key}\n{json.dumps(value, ensure_ascii=False, indent=2)}")
    blocks.append(
        "## 拆解指引\n"
        "- 任务边界：按 directory_tree 的目录/文件组切分任务，任务 files 必须落在 Spec 声明的路径内\n"
        "- 接口契约：每个任务的 contract 从 data_model 实体字段、api_contracts 名称与 component_tree 的 props 推导\n"
        "- 依赖关系：依据 component_tree 的 uses 关系与页面引用的组件/路由\n"
        "- 脚手架任务：仅当 tech_stack.build 需要（qiankun/webpack/package 等工程入口）时创建 bootstrap 任务，否则全部为 business 任务"
    )
    return blocks


def build_planner_user_prompt(
    spec: dict | None,
    design_doc: str,
    failure: dict | None = None,
) -> str:
    """Build the Planner's initial user prompt.

    Task 5.2: the Planner consumes the architecture Spec — directory_tree →
    任务边界, data_model → 接口契约, component_tree → 依赖, tech_stack/build →
    脚手架推导. When no Spec is present (legacy state) the old design-doc path
    is used as fallback.
    """
    if spec:
        parts = _spec_prompt_blocks(spec)
    else:
        parts = [f"设计方案：\n{design_doc}\n\n请拆解为可独立执行的任务。"]
    if failure:
        parts.append(
            "之前的代码存在问题：\n"
            f"{failure.get('instruction', '')}\n\n"
            "请基于上述输入重新规划任务。"
        )
    return "\n\n".join(parts)


def build_incremental_planner_prompt(
    spec: dict | None,
    design_doc: str,
    manifest: dict,
    existing_files: dict[str, str],
) -> str:
    """8.3 增量实现 — Planner 增量提示词: 只动受影响模块.

    已有文件清单 + 变更 manifest 作为上下文; 任务拆解只产出受影响模块的
    delta 任务 (新文件/待修改文件), 未受影响模块的文件绝不进入任何任务。
    """
    if spec:
        parts = _spec_prompt_blocks(spec)
    else:
        parts = [f"设计方案：\n{design_doc}"]
    if existing_files:
        file_summary = "\n".join(
            f"- {p}（{len(c)} chars）" for p, c in sorted(existing_files.items())
        )
    else:
        file_summary = "（无）"
    parts.append(
        "## 增量开发上下文（重要）\n"
        f"这是对已有应用的**增量实现**。已有文件清单（绝对不要重建/覆盖）：\n{file_summary}\n\n"
        "变更 manifest：\n"
        + json.dumps(manifest, ensure_ascii=False, indent=2)
        + "\n\n## 增量任务拆解要求\n"
        "- **只输出受影响模块的 delta 任务**：仅包含需要新建或修改的文件\n"
        "- 受影响模块 = manifest.affected_modules（含其依赖文件）;\n"
        "  未受影响模块的文件绝不允许出现在任何任务的 files 中\n"
        "- 已有文件作为只读上下文（已存在, 不作为生成目标）\n"
        "- 若变更只涉及少量文件, 合并为一个 business 任务; 保持依赖 DAG 正确;\n"
        "  task id 从 task-0 递增; 只输出 JSON"
    )
    return "\n\n".join(parts)
