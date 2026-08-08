"""Planner Agent — REASON→ACT(DAG)→OBSERVE→REFLECT loop for task decomposition."""

import json
import os

import structlog

from .tools.compile_tool import classify_compile_errors, extract_missing_paths

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


def _parse_json_tolerant(raw: str) -> dict | None:
    """Parse LLM output as JSON — fences, leading prose, truncation tolerant.

    Mirrors the Spec generator's parser: strip ```json fences → raw json.loads
    → extract the first balanced {...} block (recovers a truncated tail: the
    model hit the token ceiling mid-JSON and the complete part is still valid).
    """
    raw = (raw or "").strip()
    if not raw:
        return None
    raw_lower = raw.lower()
    if "```json" in raw_lower:
        raw = raw.split("```json", 1)[1].split("```")[0].strip()
    elif "```" in raw_lower:
        raw = raw.split("```", 1)[1].split("```")[0].strip()
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    # Fallback 1: first balanced {...} block — tolerant of leading prose.
    start = raw.find("{")
    if start >= 0:
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(raw)):
            ch = raw[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        parsed = json.loads(raw[start : i + 1])
                        return parsed if isinstance(parsed, dict) else None
                    except json.JSONDecodeError:
                        return None
    # Fallback 2: truncation tolerance — the model hit the token ceiling
    # mid-JSON and the object never closes. The last COMPLETE element ends
    # at some '}': cut there, close the remaining brackets, try again.
    # (A few attempts per '}', each a cheap local parse.)
    for i in range(len(raw) - 1, start - 1, -1):
        if raw[i] != "}":
            continue
        candidate = raw[start : i + 1]
        for suffix in ("]}", "}", "]", "}]"):
            try:
                parsed = json.loads(candidate + suffix)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                continue
    return None


def extract_task_dag(raw_json: str) -> dict:
    """Parse Planner LLM output into TaskDAG dict — truncation tolerant AND
    truncation-visible.

    The planner's DAG JSON is LARGER than the Spec JSON (each task carries
    files/contract/deps) and can hit the token ceiling: a truncated tail must
    recover the complete leading tasks, NOT fall into the hardcoded scaffold
    fallback (that produced a qiankun/webpack project for a Vite Spec). But a
    repaired tail MUST be flagged (`truncated: True`) — silently recovering a
    partial DAG drops later tasks without anyone noticing (the pipeline
    "succeeded" with 3 of 11 tasks and the missing ones were never planned).
    """
    cleaned = (raw_json or "").strip()
    low = cleaned.lower()
    if "```json" in low:
        cleaned = cleaned.split("```json", 1)[1].split("```")[0].strip()
    elif "```" in low:
        cleaned = cleaned.split("```", 1)[1].split("```")[0].strip()

    truncated = False
    parsed = None
    try:
        p = json.loads(cleaned)
        if isinstance(p, dict):
            parsed = p
    except json.JSONDecodeError:
        pass
    if parsed is None:
        # Tolerant repair (balance/truncation) — any success here means the
        # raw output did NOT parse as-is, i.e. the tail was cut off.
        parsed = _parse_json_tolerant(raw_json)
        truncated = parsed is not None
    if parsed is None:
        logger.error("planner_json_parse_failed", raw=(raw_json or "")[:200])
        raise ValueError(f"Failed to parse planner output as JSON: {(raw_json or '')[:200]}")

    # Validate and normalize tasks
    tasks = parsed.get("tasks", [])
    for t in tasks:
        t.setdefault("status", "pending")
        t.setdefault("type", "business")
        t.setdefault("deps", [])
        t.setdefault("contract", {})

    result = {
        "reasoning": parsed.get("reasoning", ""),
        "tasks": tasks,
    }
    if truncated:
        result["truncated"] = True
    return result


def _expand_directory_tree(tree: dict) -> list[str]:
    """Flatten the Spec's directory_tree into concrete file paths.

    Structure: {dir: [file_or_subdir, ...]}; subdirs are strings ending in '/'
    — expanded recursively when they have their own key, skipped otherwise
    (no file can be conjured for an undeclared subdir).
    """
    files: list[str] = []
    for dirpath, items in (tree or {}).items():
        prefix = dirpath if dirpath.endswith("/") else dirpath + "/"
        for item in items or []:
            if not isinstance(item, str):
                continue
            if item.endswith("/"):
                if item in tree:
                    files.extend(_expand_directory_tree({item: tree[item]}))
                continue
            files.append(prefix + item)
    return files


def build_spec_fallback_dag(spec: dict | None, design_doc: str) -> dict:
    """Spec-driven fallback DAG when the planner's LLM output fails to parse.

    One business task per top-level directory group from the Spec's
    directory_tree — NEVER a hardcoded scaffold: a hardcoded qiankun/webpack
    template produced a project that contradicts the Spec (e.g. Vite). Empty
    when no Spec / no files — the caller surfaces an explicit error instead
    of generating a wrong project.
    """
    if not spec:
        return {"reasoning": "", "tasks": []}
    files = _expand_directory_tree(spec.get("directory_tree") or {})
    if not files:
        return {"reasoning": "", "tasks": []}

    groups: dict[str, list[str]] = {}
    for f in files:
        top = f.split("/", 1)[0] + "/"
        groups.setdefault(top, []).append(f)

    tasks = [
        {
            "id": f"task-fallback-{i}",
            "type": "business",
            "description": f"生成 {group} 下的文件（Spec 兜底任务）",
            "deps": [],
            "files": fs,
            "contract": {},
            "status": "pending",
        }
        for i, (group, fs) in enumerate(sorted(groups.items()))
    ]
    return {
        "reasoning": "Planner 输出解析失败，已按架构 Spec 的 directory_tree 生成兜底任务",
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


# Spec sections the Planner consumes — each maps to a decomposition input:
# directory_tree → 任务边界, data_model/api_contracts → 接口契约,
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

    The Planner consumes the architecture Spec — directory_tree → 任务边界,
    data_model → 接口契约, component_tree → 依赖, tech_stack/build → 脚手架推导.
    When no Spec is present (legacy state) the old design-doc path is the fallback.
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
    missing_files: list[str],
    existing_files: dict[str, str],
) -> str:
    """Incremental replan prompt — the executor produced code that imports
    files no task generated. Replan outputs ONLY the delta tasks that produce
    those missing files; existing files are read-only context, never targets.

    This is the "execution feedback → replan" loop: a planning gap (import of
    an unplanned file) is fixed by adding tasks, not by rewriting existing
    code or blindly re-running failed tasks.
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
    missing_list = "\n".join(f"- {p}" for p in missing_files)
    parts.append(
        "## 增量重规划上下文（重要）\n"
        f"执行反馈：已生成的代码 import 了以下文件，但没有任何任务生成它们：\n{missing_list}\n\n"
        f"已生成的文件（绝对不要重建/覆盖）：\n{file_summary}\n\n"
        "## 增量任务拆解要求\n"
        "- **只输出能生成上述缺失文件的 delta 任务**：为每个缺失文件分配一个任务（文件多时可分组）\n"
        "- 缺失文件的依赖也要覆盖：若缺失文件自身 import 其他缺失文件，任务需按依赖排序\n"
        "- 已生成文件作为只读上下文（已存在，不作为生成目标）\n"
        "- 任务契约从 Spec 的 data_model / api_contracts / component_tree 推导\n"
        "- task id 从 task-0 开始递增；只输出 JSON"
    )
    return "\n\n".join(parts)


def plan_final_compile_fix(
    errors: list[dict],
    fix_round: int = 0,
    max_fix_rounds: int = 3,
) -> dict:
    """Decide the response to a failed FINAL full compile.

    The final full compile (esbuild + vue-tsc) is the last gate after all
    tasks are done — vue-tsc type errors only surface here, and so do missing
    files that were never planned. Generation must NOT just stop on failure;
    the errors are fed back into the loop:

      "done"   — compile passed (or no errors), nothing to do
      "replan" — every error is a missing-import signal → incremental
                 planner emits delta tasks for the missing files
      "fix"    — real code/type defects → a repair task targets the failing
                 files (executor re-engages with the error list)
      "abort"  — env errors (nothing to fix in code), no extractable paths,
                 or the fix-round budget is exhausted

    Returns: {"action", "reason", "missing_files"|"fix_files", ...}
    """
    if not errors:
        return {"action": "done", "reason": "最终编译通过"}

    if fix_round >= max_fix_rounds:
        return {"action": "abort", "reason": f"超过最大修复轮次（{max_fix_rounds} 轮）"}

    kind = classify_compile_errors(errors)
    if kind == "env":
        return {
            "action": "abort",
            "reason": "最终编译失败是环境错误（如项目目录不存在/编译服务不可达），没有可修复的代码",
        }

    if kind == "missing_file":
        missing_files = extract_missing_paths(errors)
        if missing_files:
            return {
                "action": "replan",
                "missing_files": missing_files,
                "reason": f"最终编译发现 {len(missing_files)} 个未生成文件，增量重规划",
            }
        return {"action": "abort", "reason": "缺失文件错误但无法提取路径，无法重规划"}

    # code (or mixed): repair task over the files carrying errors
    fix_files = sorted({
        e.get("file", "") for e in errors
        if e.get("file") and e.get("kind") != "env"
    })
    if fix_files:
        return {
            "action": "fix",
            "fix_files": fix_files,
            "reason": f"最终编译有 {len(errors)} 个代码错误，创建修复任务",
        }
    return {"action": "abort", "reason": "代码错误但没有带文件信息的条目，无法定位修复目标"}


def build_feedback_planner_prompt(
    design_doc: str,
    generated_files: dict[str, str],
    feedback_history: dict | None,
    code_feedback: str,
    project_root: str = "",
) -> str:
    """Feedback replan prompt — the planner sees the project's ACTUAL state
    (generated files with sizes, last compile errors, failed tasks) plus the
    user's feedback verbatim. No keyword parsing: any input goes through this
    same path and the agent decides what (if anything) needs doing. The facts
    are prompt context (allowed), never displayed verbatim as agent speech.
    """
    history = feedback_history or {"compile_errors": [], "failed_tasks": []}

    file_lines = []
    for path, content in generated_files.items():
        try:
            size = f"{os.path.getsize(os.path.join(project_root, path))} B"
        except OSError:
            size = f"{len(content)} chars"
        file_lines.append(f"- {path} ({size})")
    if not file_lines:
        file_lines = ["(无)"]

    compile_lines = [
        f"- [{e.get('source', '')}] {e.get('file', '?')}:{e.get('line', 0)} — {e.get('message', '')}"
        for e in history.get("compile_errors", [])
    ] or ["(无)"]

    failed_lines = [
        f"- {t.get('id', '?')} ({t.get('description', '')}): "
        f"failure={t.get('failure_kind')}, 缺: {', '.join(t.get('missing_paths', []) or [])}"
        for t in history.get("failed_tasks", [])
    ] or ["(无)"]

    return (
        f"设计方案：\n{design_doc}\n\n"
        f"## 项目现场（已生成文件，只读，不得重建/覆盖）\n"
        + "\n".join(file_lines)
        + "\n\n## 上次最终编译状态\n"
        + "\n".join(compile_lines)
        + "\n\n## 失败任务（执行记录）\n"
        + "\n".join(failed_lines)
        + f"\n\n用户反馈：{code_feedback}\n\n"
        f"请基于项目现场与用户反馈判断需要做什么："
        f"需要修改时输出补充 Task DAG（仅包含需要新增或修改的任务）；"
        f"无需修改时输出空 tasks 列表。"
    )


def is_empty_delta_tolerable(code_feedback: str | None, parse_succeeded: bool) -> bool:
    """An empty task list is a legit "no changes needed" verdict ONLY when the
    model actually produced it (clean parse) AND a user feedback triggered the
    replan — the planner reviewed the recovered project state and judged
    nothing needs doing. Parse failures never count: they must surface as
    errors, not as a silent "nothing to do"."""
    return bool(code_feedback) and parse_succeeded


def build_fix_task(
    fix_round: int,
    fix_files: list[str],
    errors: list[dict],
) -> dict:
    """A repair task that re-engages the executor on files failing the final
    full compile. The error list rides in ``contract.errors`` so the executor
    sees the exact defects; it runs with full-compile verification (the type
    errors that quick checks can't see).
    """
    error_summary = "\n".join(
        f"- {e.get('file') or '?'}:{e.get('line', 0)} {e.get('message', '')}"[:300]
        for e in errors[:10]
    )
    return {
        "id": f"task-fix-{fix_round}",
        "type": "fix",
        "description": (
            f"修复最终编译错误（第 {fix_round + 1} 轮），目标文件：{', '.join(fix_files)}\n"
            f"{error_summary}"
        ),
        "deps": [],
        "files": fix_files,
        "contract": {"errors": errors[:20]},
        "status": "pending",
    }


def merge_delta_tasks(tasks: list[dict], delta_tasks: list[dict]) -> int:
    """Merge incremental-planner delta tasks into the DAG.

    The incremental planner restarts task ids at task-0 — clashing with ids
    already in the DAG (failed tasks keep their ids). Renumber clashing deltas
    instead of dropping them: a dropped delta means the missing file is never
    produced and the loop dead-ends. Returns the number merged.
    """
    existing_ids = {t["id"] for t in tasks}
    merged = 0
    for dt in delta_tasks:
        if dt["id"] in existing_ids:
            n = 0
            while f"task-delta-{n}" in existing_ids:
                n += 1
            dt["id"] = f"task-delta-{n}"
        existing_ids.add(dt["id"])
        dt["status"] = "pending"
        tasks.append(dt)
        merged += 1
    return merged
