"""应用记忆 (task group 7) — persistent project_root + `.ai-memory/` 读写 + 恢复/增量加载.

四层记忆 (D8):
- ① 短期 run_context   —— 本次运行快照,写透到 `.ai-memory/state/run_context.json` 暂存区。
- ② 中期 运行轨迹/问题 — SQLite (memory_db.py),按 generation 归档。
- ③ 长期用户级         —— SQLite (memory_db.py),挂 user 维度。
- ④ 长期应用级         —— 本模块:`.ai-memory/` 目录随生成仓走。

本模块职责:
- ``project_root_for`` — project_root 的唯一来源 (7.1): 从 `tempfile.gettempdir()`
  迁移到持久目录 ``<AI_GEN_DATA_DIR>/generated/<app_id>/`` (env 可配,默认
  ``./data``,相对 ai-service 工作目录)。app_id 由 state 的 generation_id
  (或 requirement 哈希) 一致推导。
- ``.ai-memory/`` 目录结构与全部写助手 (7.2),生成期持续写入 (7.3),
  run_context 暂存 (7.4),崩溃恢复加载 (7.7),增量开发加载摘要 + diff 原语 (7.8)。
- 所有写操作 fail-open: 失败只记日志,绝不阻塞流水线。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from typing import Any

import structlog

from .state import GenerationState

logger = structlog.get_logger()

# ── Constants ──

MEMORY_VERSION = 1
SPEC_VERSION = 1  # mirrors spec_schema.SPEC_VERSION

MEMORY_DIR = ".ai-memory"
SPEC_DIR = "spec"
STATE_DIR = "state"
CHANGES_DIR = "changes"

INDEX_PATH = os.path.join(MEMORY_DIR, "index.json")
REQUIREMENTS_PATH = os.path.join(MEMORY_DIR, SPEC_DIR, "requirements.md")
ARCHITECTURE_JSON_PATH = os.path.join(MEMORY_DIR, SPEC_DIR, "architecture.json")
ARCHITECTURE_MD_PATH = os.path.join(MEMORY_DIR, SPEC_DIR, "architecture.md")
DECISIONS_PATH = os.path.join(MEMORY_DIR, SPEC_DIR, "decisions.md")
STATE_JSON_PATH = os.path.join(MEMORY_DIR, STATE_DIR, "state.json")
CONTRACTS_JSON_PATH = os.path.join(MEMORY_DIR, STATE_DIR, "contracts.json")
RUN_CONTEXT_PATH = os.path.join(MEMORY_DIR, STATE_DIR, "run_context.json")
PROBLEMS_PATH = os.path.join(MEMORY_DIR, "problems.jsonl")

# 7.8 增量加载: requirements/architecture 摘要截断上限 (字符)。
SUMMARY_CHAR_LIMIT = 1500

# 代码阶段完成时的 generated_files 扫描排除目录。
_SCAN_EXCLUDE = {".ai-memory", "node_modules", "e2e", ".git", "dist", "vitest", "coverage", ".vite"}

# 扫描排除文件 (review M7): 大体积/文档类文件不进代码清单 (planner 上下文
# 会爆炸, 且它们不是生成目标)。
_SCAN_EXCLUDE_FILES = {"package-lock.json", "pnpm-lock.yaml", "yarn.lock", "README.md", "README"}

# ── 7.1 持久 project_root ──


def data_dir() -> str:
    """持久数据根目录 — env ``AI_GEN_DATA_DIR`` (默认 ``<cwd>/data``)."""
    return os.environ.get("AI_GEN_DATA_DIR", os.path.join(os.getcwd(), "data"))


def sanitize_app_id(raw: str) -> str:
    """Windows-safe app_id 清洗 (生成目录名用, 防路径穿越)."""
    safe = re.sub(r"[^\w.-]", "_", raw or "")
    return safe[:120].strip("._") or "ai-gen-app"


def app_id_for(state: GenerationState) -> str:
    """推导 app_id: 优先 generation_id (崩溃恢复/续跑需要一致), 否则
    requirement 的确定性 slug + 短哈希 (不同需求互不碰撞)."""
    gid = state.get("generation_id")
    if gid:
        return sanitize_app_id(gid)
    raw = (state.get("requirement") or "project")[:60]
    safe = re.sub(r"[^\w]", "_", raw)[:30].strip("_") or "ai-gen-project"
    h = hashlib.md5((state.get("requirement") or "").encode("utf-8")).hexdigest()[:8]
    return f"{safe}-{h}"


def app_dir_for(app_id: str) -> str:
    """生成应用根目录: ``<data_dir>/generated/<app_id>``."""
    return os.path.join(data_dir(), "generated", sanitize_app_id(app_id))


def project_root_for(state: GenerationState) -> str:
    """The generated-app project root — 全流水线唯一来源 (7.1).

    替换 graph.py / nodes.py / spec_schema.py / e2e_designer.py 中所有
    ``tempfile.gettempdir()/ai-gen/<safe_name>`` 的计算, 运行时状态随
    ``data/generated/<app_id>/`` 持久化。
    """
    return app_dir_for(app_id_for(state))


# ── 7.2 `.ai-memory/` 目录结构: 写助手 (全部 fail-open) ──


def ensure_memory_dir(project_root: str) -> str | None:
    """创建 .ai-memory/{spec,state,changes} 目录树; 失败返回 None (fail-open)."""
    try:
        for sub in ("", SPEC_DIR, STATE_DIR, CHANGES_DIR):
            os.makedirs(os.path.join(project_root, MEMORY_DIR, sub), exist_ok=True)
        return os.path.join(project_root, MEMORY_DIR)
    except OSError as e:
        logger.warning("memory_dir_failed", project_root=project_root, error=str(e))
        return None


def _read_json(project_root: str, rel: str) -> Any | None:
    try:
        with open(os.path.join(project_root, rel), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _read_text(project_root: str, rel: str) -> str | None:
    try:
        with open(os.path.join(project_root, rel), encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def _atomic_write(path: str, writer) -> str | None:
    """原子写: 先写同目录临时文件再 os.replace (M4) — 崩溃恢复检查点
    不会被截断的中间态损坏 (Windows 下 os.replace 对同卷原子)."""
    tmp = f"{path}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            writer(f)
        os.replace(tmp, path)
        return path
    except OSError as e:
        logger.warning("memory_write_failed", path=path, error=str(e))
        try:
            os.remove(tmp)
        except OSError:
            pass
        return None


def _write_json(project_root: str, rel: str, payload: Any) -> str | None:
    root = ensure_memory_dir(project_root)
    if root is None:
        return None
    path = os.path.join(project_root, rel)
    return _atomic_write(path, lambda f: json.dump(payload, f, ensure_ascii=False, indent=2))


def _write_text(project_root: str, rel: str, text: str) -> str | None:
    root = ensure_memory_dir(project_root)
    if root is None:
        return None
    path = os.path.join(project_root, rel)
    return _atomic_write(path, lambda f: f.write(text))


def _ts() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def read_index(project_root: str) -> dict:
    """index.json 内容 (缺失/损坏 → {})."""
    data = _read_json(project_root, INDEX_PATH)
    return data if isinstance(data, dict) else {}


def update_index(
    project_root: str,
    *,
    stage: str | None = None,
    features_done: list[str] | None = None,
    app_id: str | None = None,
    verdicts: list[dict] | None = None,
    reset: bool = False,
) -> dict | None:
    """更新 ``.ai-memory/index.json`` (不存在则创建) — 清单/阶段完成/功能完成.

    ``stage`` 标为 "done"; ``features_done`` 覆盖功能完成清单;
    ``verdicts`` 持久化把关裁决日志 (M1: 崩溃恢复后 decisions.md 不丢历史);
    ``reset`` 清空 stages/features_done/verdicts (I3: skip_analysis 全量重来
    时旧运行标记不得被后续崩溃恢复误读)。
    返回新 index 或 None (fail-open)。
    """
    root = ensure_memory_dir(project_root)
    if root is None:
        return None
    index = read_index(project_root)
    if not index:
        index = {
            "app_id": app_id or os.path.basename(os.path.normpath(project_root)),
            "created_at": _ts(),
            "version": MEMORY_VERSION,
            "spec_version": SPEC_VERSION,
            "features_done": [],
            "stages": {},
        }
    index["updated_at"] = _ts()
    if reset:
        index["stages"] = {}
        index["features_done"] = []
        index.pop("verdicts", None)
    if stage:
        index.setdefault("stages", {})[stage] = "done"
    if features_done is not None:
        index["features_done"] = sorted(set(features_done))
    if verdicts is not None:
        index["verdicts"] = list(verdicts)
    _write_json(project_root, INDEX_PATH, index)
    return index


def write_requirements(project_root: str, prd: str) -> str | None:
    """全量需求规格 → ``spec/requirements.md`` (需求分析节点完成时)."""
    return _write_text(project_root, REQUIREMENTS_PATH, prd or "")


def write_spec(project_root: str, spec: dict) -> str | None:
    """架构 Spec → ``spec/architecture.json`` (D5 同构, 唯一格式, 4.5 由本模块接管)."""
    return _write_json(project_root, ARCHITECTURE_JSON_PATH, spec or {})


def write_architecture_md(project_root: str, design_doc: str) -> str | None:
    """人读设计文档 → ``spec/architecture.md``."""
    return _write_text(project_root, ARCHITECTURE_MD_PATH, design_doc or "")


def _render_decisions(state: GenerationState) -> str:
    """决策日志渲染: 头脑风暴决策 + Manager 把关裁决 (state 为准, 幂等重写)."""
    lines = ["# 决策日志", ""]
    lines.append("## 头脑风暴决策")
    decisions = state.get("brainstorm_decisions") or []
    if not decisions:
        lines.append("（无）")
    for d in decisions:
        lines.append(
            f"- **{d.get('topic', '?')}**：{d.get('choice', '')} — {d.get('reason', '')}"
            f"（{d.get('at', '')}，round {d.get('round', '?')}）"
        )
    lines += ["", "## Manager 把关裁决"]
    verdicts = state.get("manager_verdicts") or []
    if not verdicts:
        lines.append("（无）")
    for v in verdicts:
        lines.append(
            f"- **{v.get('node', '?')}**：{v.get('decision', '')} — {v.get('reason', '')}"
            f"（{v.get('at', '')}，sig {v.get('signature', '')}）"
        )
    return "\n".join(lines) + "\n"


def write_decisions(project_root: str, state: GenerationState) -> str | None:
    """决策日志 → ``spec/decisions.md`` (把关裁决/方案对比留痕)."""
    return _write_text(project_root, DECISIONS_PATH, _render_decisions(state))


def _derive_state(state: GenerationState) -> dict:
    """state/state.json 派生: features (requirements_state_json 或 PRD 解析)
    + implemented (planner_dag 已完成任务) + milestones."""
    features: list[dict] = []
    req_json = state.get("requirements_state_json")
    if req_json:
        try:
            data = json.loads(req_json)
        except (json.JSONDecodeError, TypeError):
            data = None
        if isinstance(data, dict):
            for i, f in enumerate(data.get("features") or [], start=1):
                if not isinstance(f, dict):
                    continue
                features.append({
                    "id": f.get("id") or f"F-{i:02d}",
                    "name": f.get("name") or f.get("title") or "",
                    "priority": f.get("priority", ""),
                    "status": "planned",
                })
    if not features:
        for i, name in enumerate(extract_feature_names(state.get("analysis_result") or ""), start=1):
            features.append({"id": f"F-{i:02d}", "name": name, "priority": "", "status": "planned"})

    dag = state.get("planner_dag") or {}
    tasks = dag.get("tasks") or []
    done = [t for t in tasks if isinstance(t, dict) and t.get("status") == "done"]
    implemented = [t.get("id", "?") for t in done]
    return {
        "features": features,
        "implemented": implemented,
        "milestones": {
            "total_tasks": dag.get("total_tasks", len(tasks)),
            "completed_tasks": dag.get("completed_tasks", len(done)),
            "planner_reflect_count": state.get("planner_reflect_count", 0),
        },
        "updated_at": _ts(),
    }


def write_state(project_root: str, state: GenerationState) -> str | None:
    """功能状态 → ``state/state.json`` (代码阶段完成时)."""
    return _write_json(project_root, STATE_JSON_PATH, _derive_state(state))


def write_incremental_state(project_root: str, state: GenerationState) -> str | None:
    """8.6 增量变更完成 — state.json 功能状态推进 (合并已有 + 本次新增).

    已有 features/implemented/milestones 保留; 本次新增的 feature 追加
    (id 去重), implemented 取并集, milestones 计数累加并记 ``incremental_revisions``。
    """
    old = _read_json(project_root, STATE_JSON_PATH)
    old = old if isinstance(old, dict) else {}
    derived = _derive_state(state)

    by_id: dict[str, dict] = {}
    for f in old.get("features") or []:
        if isinstance(f, dict) and f.get("id"):
            by_id[f["id"]] = dict(f)
    for f in derived.get("features") or []:
        if not isinstance(f, dict) or not f.get("id"):
            continue
        if f["id"] not in by_id:
            by_id[f["id"]] = f

    implemented = sorted(
        set((old.get("implemented") or [])) | set((derived.get("implemented") or []))
    )
    old_ms = old.get("milestones") or {}
    new_ms = derived.get("milestones") or {}
    merged = {
        "features": list(by_id.values()),
        "implemented": implemented,
        "milestones": {
            "total_tasks": int(old_ms.get("total_tasks") or 0)
            + int(new_ms.get("total_tasks") or 0),
            "completed_tasks": int(old_ms.get("completed_tasks") or 0)
            + int(new_ms.get("completed_tasks") or 0),
            "planner_reflect_count": new_ms.get("planner_reflect_count", 0),
            "incremental_revisions": int(old_ms.get("incremental_revisions") or 0) + 1,
        },
        "updated_at": _ts(),
    }
    return _write_json(project_root, STATE_JSON_PATH, merged)


def update_index_revision(project_root: str, change_id: str) -> dict | None:
    """8.6 增量变更完成 — index.json 版本推进 (change_revision + last_change_id)."""
    root = ensure_memory_dir(project_root)
    if root is None:
        return None
    index = read_index(project_root)
    index["change_revision"] = (index.get("change_revision") or 0) + 1
    index["last_change_id"] = change_id
    index["updated_at"] = _ts()
    return _write_json(project_root, INDEX_PATH, index)


def write_contracts(project_root: str, contracts: dict | None) -> str | None:
    """文件接口契约 → ``state/contracts.json`` (context_summary 持久化)."""
    return _write_json(project_root, CONTRACTS_JSON_PATH, contracts or {})


def append_problem(
    project_root: str,
    *,
    category: str,
    problem: str,
    root_cause: str = "",
    fix: str = "",
    result: str = "",
) -> str | None:
    """问题留痕 → ``problems.jsonl`` 追加一行 (诊断/修复闭环)."""
    root = ensure_memory_dir(project_root)
    if root is None:
        return None
    record = {
        "ts": _ts(),
        "category": category,
        "problem": problem,
        "root_cause": root_cause,
        "fix": fix,
        "result": result,
    }
    path = os.path.join(project_root, PROBLEMS_PATH)
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return path
    except OSError as e:
        logger.warning("problems_append_failed", path=path, error=str(e))
        return None


def read_problems(project_root: str) -> list[dict]:
    """problems.jsonl 全量读取 (测试/调试用)."""
    text = _read_text(project_root, PROBLEMS_PATH)
    if not text:
        return []
    records = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


# ── 7.4 短期记忆 run_context: 快照 + 写透到暂存区 ──


def update_run_context(state: GenerationState, **updates: Any) -> dict:
    """更新 ``state.run_context`` 并写透到 ``.ai-memory/state/run_context.json``.

    各阶段切换时调用 (阶段开始/完成/把关裁决/问题记录); 写入 fail-open。
    未显式提供的议程/假设/决策从 state 现有字段继承。
    """
    ctx = dict(state.get("run_context") or {})
    ctx.update(updates)
    if "agenda" not in ctx:
        ctx["agenda"] = []
    if "assumptions" not in ctx:
        ctx["assumptions"] = state.get("brainstorm_assumptions") or []
    if "decisions" not in ctx:
        ctx["decisions"] = state.get("brainstorm_decisions") or []
    if "generation_id" not in ctx:
        ctx["generation_id"] = state.get("generation_id", "")
    ctx["updated_at"] = _ts()
    state["run_context"] = ctx
    root = project_root_for(state)
    _write_json(root, RUN_CONTEXT_PATH, ctx)  # 暂存区写透 (fail-open)
    return ctx


# ── 7.3 生成期持续写入: 阶段完成 / 把关 / 问题 ──


def init_app_memory(state: GenerationState, *, reset: bool = False) -> None:
    """生成初始化: 创建 .ai-memory/ 目录 + index.json 清单 (spec 场景).

    ``reset=True`` (I3): 全量重来 (skip_analysis / 无恢复) 时清空旧运行的
    阶段完成标记, 防止后续崩溃恢复误读上一轮运行的状态。
    """
    root = project_root_for(state)
    update_index(root, app_id=app_id_for(state), reset=reset)
    update_run_context(state)


def persist_stage_artifacts(state: GenerationState, stage: str) -> None:
    """7.3 节点完成写 spec/state/contracts + 阶段完成标记 (fail-open).

    - analysis: requirements.md 全量写入 (把关重做时覆盖重写);
    - design: architecture.md + architecture.json (仅把关通过, 与 4.5 语义一致);
    - code: state.json (features/implemented) + contracts.json (context_summary);
    阶段在 index.json 标记 done 仅在对应把关裁决为 pass 时 (崩溃恢复以此为准)。
    """
    root = project_root_for(state)
    verdicts = state.get("manager_verdicts") or []
    last_for_stage = next((v for v in reversed(verdicts) if v.get("node") == stage), None)
    passed = bool(last_for_stage and last_for_stage.get("decision") == "pass")

    if stage == "analysis":
        write_requirements(root, state.get("analysis_result") or "")
    elif stage == "design":
        if passed and state.get("architecture_spec"):
            write_spec(root, state.get("architecture_spec"))
            write_architecture_md(root, state.get("design_doc") or state.get("design_result") or "")
    elif stage == "code":
        write_state(root, state)
        write_contracts(root, state.get("context_summary"))

    if passed:
        update_index(root, stage=stage)
        if stage == "code":
            state_json = _derive_state(state)
            update_index(root, features_done=[
                f.get("id") for f in state_json.get("features", []) if f.get("id")
            ])


def record_problem(
    state: GenerationState,
    *,
    category: str,
    problem: str,
    root_cause: str = "",
    fix: str = "",
    result: str = "",
) -> None:
    """问题记录 → .ai-memory/problems.jsonl + 中期 problem_records + 长期
    失败模式/修复策略 (fail-open, 绝不阻断)."""
    root = project_root_for(state)
    append_problem(
        root,
        category=category,
        problem=problem,
        root_cause=root_cause,
        fix=fix,
        result=result,
    )
    update_run_context(state, latest_problem={
        "category": category,
        "problem": (problem or "")[:200],
        "result": result,
        "ts": _ts(),
    })
    try:
        from .memory_db import get_memory_db

        db = get_memory_db()
        gid = state.get("generation_id") or "unknown"
        db.append_problem(gid, category, problem, root_cause, fix, result)
        user_id = state.get("user_id") or "default"
        db.record_failure_pattern(user_id, category, problem, fix or root_cause)
        # 修复策略统计: 有修复动作 → 尝试 +1; 闭环通过 → 成功 +1。
        strategy = (fix or root_cause or "")[:120]
        if strategy:
            db.record_fix_strategy_success(category, strategy)
            if result == "passed":
                db.record_fix_strategy_result(category, strategy, success=True)
    except Exception as e:  # pragma: no cover - fail-open
        logger.warning("memory_db_problem_record_failed", error=str(e))


# ── 7.7 崩溃恢复: 从 .ai-memory/ 重建 state 补丁 ──


def _completed_stages(project_root: str) -> set[str]:
    """已完成阶段: index.json 存在时**以 index 为准** (I3 — skip_analysis
    重置后空 stages = 全新开始, 旧产物不得被误恢复)。

    兜底 (index 文件缺失时): 仅按**过关才会写**的产物推断 — requirements.md
    (analysis 完成即写) 与 architecture.json/architecture.md (design 过关才写)。
    state.json 不参与兜底 (code 阶段 redo 时也会写, 会误把失败尝试当成完成 —
    M3); code 阶段完成只认 index 标记。
    """
    if os.path.isfile(os.path.join(project_root, INDEX_PATH)):
        index = read_index(project_root)
        return {
            s for s, v in (index.get("stages") or {}).items() if v == "done"
        }
    present: set[str] = set()
    if _read_text(project_root, REQUIREMENTS_PATH):
        present.add("analysis")
    if _read_json(project_root, ARCHITECTURE_JSON_PATH) is not None:
        present.add("design")
    if _read_text(project_root, ARCHITECTURE_MD_PATH):
        present.add("design")
    return present


def scan_generated_files(project_root: str) -> dict[str, str]:
    """扫描生成仓 (排除 .ai-memory/node_modules/e2e/构建产物) → 代码文件映射."""
    files: dict[str, str] = {}
    if not os.path.isdir(project_root):
        return files
    for dirpath, dirnames, filenames in os.walk(project_root):
        dirnames[:] = [d for d in dirnames if d not in _SCAN_EXCLUDE]
        for fn in filenames:
            if fn in _SCAN_EXCLUDE_FILES:
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, project_root)
            try:
                with open(full, encoding="utf-8") as f:
                    files[rel.replace("\\", "/")] = f.read()
            except (OSError, UnicodeDecodeError):
                continue
    return files


def load_app_state(
    project_root: str,
    generation_id: str,
) -> dict | None:
    """7.7 崩溃恢复 — 依据 ``.ai-memory/`` 重建 GenerationState 补丁.

    已完成阶段 (index.json stages, 产物存在性兜底) 恢复其产物:
    - analysis → analysis_result (spec/requirements.md);
    - design → architecture_spec (architecture.json) + design_result/design_doc
      (architecture.md);
    - code → generated_files (磁盘扫描) + code_result。

    未完成阶段 (进行中崩溃) 不恢复产物 → 由既有 phase-skip 逻辑重跑该阶段
    (进行中续跑为 best-effort: run_context.json 暂存区保留最近运行状态,
    U9 恢复阶梯在其上构建)。无任何记忆产物 → None。
    """
    stages = _completed_stages(project_root)
    if not stages:
        return None

    # M1: 恢复 index 中持久化的把关裁决日志 — 恢复后 write_decisions 重写
    # decisions.md 时不会丢掉已完成阶段的历史裁决。
    index = read_index(project_root)
    stored_verdicts = index.get("verdicts") or []
    verdicts = [v for v in stored_verdicts if isinstance(v, dict)] if isinstance(stored_verdicts, list) else []

    patch: dict = {"generation_id": generation_id, "manager_verdicts": verdicts}
    patched_any = False

    if "analysis" in stages:
        text = _read_text(project_root, REQUIREMENTS_PATH)
        if text:
            patch["analysis_result"] = text
            patched_any = True
    if "design" in stages:
        spec = _read_json(project_root, ARCHITECTURE_JSON_PATH)
        doc = _read_text(project_root, ARCHITECTURE_MD_PATH)
        if spec is not None:
            patch["architecture_spec"] = spec
            patched_any = True
        if doc:
            patch["design_result"] = doc
            patch["design_doc"] = doc
            patched_any = True
    if "code" in stages:
        files = scan_generated_files(project_root)
        if files:
            patch["generated_files"] = files
            patch["code_result"] = json.dumps(files, ensure_ascii=False)
            patch["compile_errors"] = None
            patched_any = True

    ctx = _read_json(project_root, RUN_CONTEXT_PATH)
    if isinstance(ctx, dict):
        patch["run_context"] = ctx

    if not patched_any:
        return None
    return patch


# ── 7.8 增量开发加载: 摘要 + 按需检索 + diff 原语 ──


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n…（已截断，全文 {len(text)} 字符，可用 load_section 按需读取）"


def _architecture_summary(spec: dict) -> dict:
    """架构 Spec 结构化摘要 (页/组件/数据实体名 + 技术栈), 不整包加载."""
    return {
        "tech_stack": spec.get("tech_stack") or {},
        "pages": [p.get("name") for p in (spec.get("pages") or []) if isinstance(p, dict)],
        "components": [c.get("name") for c in (spec.get("component_tree") or []) if isinstance(c, dict)],
        "data_entities": [e.get("name") for e in (spec.get("data_model") or []) if isinstance(e, dict)],
        "decisions_count": len(spec.get("decisions") or []),
        "spec_version": spec.get("spec_version"),
    }


def load_summary(project_root: str) -> dict | None:
    """7.8 增量开发加载摘要: state.json + decisions.md 全量; requirements.md /
    architecture.json 摘要; 细节按需 ``load_section``。无记忆 → None。"""
    index = read_index(project_root)
    if not index and _read_text(project_root, REQUIREMENTS_PATH) is None:
        return None

    state_json = _read_json(project_root, STATE_JSON_PATH)
    state_json = state_json if isinstance(state_json, dict) else {}
    decisions = _read_text(project_root, DECISIONS_PATH) or ""
    requirements = _read_text(project_root, REQUIREMENTS_PATH) or ""
    spec = _read_json(project_root, ARCHITECTURE_JSON_PATH)

    return {
        "app_id": index.get("app_id") or os.path.basename(os.path.normpath(project_root)),
        "index": index,
        "state": state_json,                        # 全量 (小)
        "decisions": decisions,                     # 全量 (小)
        "requirements_summary": _truncate(requirements, SUMMARY_CHAR_LIMIT),
        "requirements_size": len(requirements),
        "architecture_summary": _architecture_summary(spec) if isinstance(spec, dict) else None,
        "features": [
            f.get("name") for f in state_json.get("features") or []
            if isinstance(f, dict) and f.get("name")
        ],
    }


def load_section(project_root: str, rel_path: str) -> str | None:
    """按需全量读取 .ai-memory 下的指定文件 (如 "spec/requirements.md" 或
    ".ai-memory/spec/requirements.md"). 路径必须落在 .ai-memory/ 内
    (防目录穿越)。返回文本或 None。
    """
    rel = rel_path.replace("\\", "/").lstrip("/")
    if rel.startswith(MEMORY_DIR + "/"):
        rel = rel[len(MEMORY_DIR) + 1:]
    base = os.path.abspath(os.path.join(project_root, MEMORY_DIR))
    full = os.path.abspath(os.path.join(base, rel))
    if not full.startswith(base + os.sep):
        logger.warning("memory_load_section_outside", rel_path=rel_path)
        return None
    return _read_text(base, rel)


_MODULE_HEADING = re.compile(r"^#{1,6}\s*[0-9.]*\s*功能模块", re.M)
_NEXT_HEADING = re.compile(r"\n#{1,6}\s")
_BULLET = re.compile(r"^\s*(?:[-*]|\d+\.)\s+(?:\*\*)?([^*\n（(：:]+)", re.M)


def _clean_module_name(raw: str) -> str:
    for sep in ("：", ":", "（", "("):
        idx = raw.find(sep)
        if idx != -1:
            raw = raw[:idx]
    return raw.strip()


def extract_feature_names(text: str) -> list[str]:
    """从需求文本 (PRD / 新需求) 提取功能点名称清单 (轻量确定性解析).

    ``功能模块`` 章节的子弹列表为准; 无该章节时回退到任意顶层子弹。
    """
    text = text or ""
    m = _MODULE_HEADING.search(text)
    if m:
        section = text[m.end():]
        end = _NEXT_HEADING.search(section)
        if end:
            section = section[:end.start()]
        names = [_clean_module_name(b) for b in _BULLET.findall(section)]
    else:
        names = []
        for line in text.splitlines():
            b = _BULLET.match(line)
            if b:
                names.append(_clean_module_name(b.group(1)))
    seen: set[str] = set()
    out: list[str] = []
    for n in names:
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def diff_requirement(base: dict, new_requirement: str) -> dict:
    """7.8 diff 原语 — 已加载应用记忆摘要 vs 新需求的**功能点清单 diff**.

    ``base`` 为 ``load_summary`` 输出 (或含 ``features`` 键的 dict);
    ``new_requirement`` 为新需求文本 (增量 PRD 或用户描述)。

    Returns ``{added, removed, unchanged, modified, note}`` —
    modified (语义级变更) 由 U8 变更 manifest 阶段判定, 本原语只提供
    功能点增量骨架。
    """
    old = [str(n).strip() for n in (base.get("features") or []) if n]
    new = extract_feature_names(new_requirement)
    old_set, new_set = set(old), set(new)
    return {
        "added": sorted(new_set - old_set),
        "removed": sorted(old_set - new_set),
        "unchanged": sorted(old_set & new_set),
        "modified": [],
        "note": "modified（行为变更）由变更 manifest（U8）语义判定",
    }
