"""Incremental development workflow (task group 8) — diff → manifest →
test-impact dispositions → changes/ records → regression accounting.

On top of the U7 memory system this module delivers the incremental pipeline:

- **8.1 diff classification** — ``classify_diff``: the deterministic
  name-identity skeleton (``memory.diff_requirement``) plus an LLM pass that
  detects *semantic* modifications of existing features (from/to descriptions).
  Fail-safe: LLM garbage → the deterministic skeleton (modified empty).
- **8.2 change manifest** — ``generate_manifest``: structured LLM producing the
  D9 shape ``{change_id, type, affected_modules, affected_requirement_points,
  behavior_changes}``, schema-validated with a fail-safe ``new_feature``
  default. Diagnoser-compatible derivations (``changed_requirements`` /
  ``changes``) are computed deterministically — the Diagnoser's expected_broken
  classification keys off *behavior* changes, so a new-feature manifest never
  masks a real regression.
- **8.4 test impact** — ``analyze_test_impact``: deterministic per-case
  dispositions (retire = requirement point removed; update = point in
  affected_requirement_points; fix-selector = refactor + fragile css/role
  selector; keep otherwise); ``apply_dispositions`` maps retire → archived,
  update → expected_broken (kept in the case version history, 6.6).
- **8.5 regression accounting** — ``build_regression_accounting``: per-case
  status accounting (active red → diagnosis classification; expected_broken
  red → expected; archived → not run); ``record_regression_results`` writes
  the run summary into ``.ai-memory/changes/<change_id>.json``.
- **8.6 memory update** — ``finalize_incremental_change``: finalizes the
  changes/ record (diff, manifest, affected files, case results, verdict),
  merges ``state.json`` feature progression and bumps the index revision.

All writes are fail-open (log, never block). The module is pure stdlib +
structlog + the existing seams (``brainstorm._llm_structured`` /
``memory`` writers) — no nodes import, so nodes/graph can import it without
cycles.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

import structlog

from .state import GenerationState
from .e2e_designer import (
    STATUS_ACTIVE,
    STATUS_ARCHIVED,
    STATUS_EXPECTED_BROKEN,
    normalize_requirement_id,
    update_case_statuses,
)

logger = structlog.get_logger()

# ── Constants ──

MANIFEST_TYPES = ("new_feature", "behavior_change", "refactor", "visual")

DEFAULT_MANIFEST_TYPE = "new_feature"

DISP_KEEP = "keep"
DISP_UPDATE = "update"
DISP_RETIRE = "retire"
DISP_FIX_SELECTOR = "fix-selector"

_FRAGILE_BY = ("css", "role")


# ── LLM seam (lazy: nodes ↔ incremental cycle) ──

def _default_llm(system_prompt: str, user_content: str) -> Any:
    from .nodes import _llm_generate  # lazy

    return _llm_generate(system_prompt, user_content)


# ── 8.1 Diff classification ──

DIFF_SCHEMA: dict = {
    "added": [""],
    "removed": [""],
    "modified": [{"name": "", "from": "", "to": ""}],
    "unchanged": [""],
    "note": "",
}

DIFF_SYSTEM_PROMPT = """你是增量开发的需求变更分析师。对照已有应用的功能点清单与用户的新需求，判断哪些既有功能点发生了**行为变更**（修改），哪些是新增/删除。

## 输入
- 已有功能点清单：{"id": "R-01", "name": "分页功能"}
- 用户新需求文本

## 输出（只输出 JSON）
{
  "added": ["新增功能点名称（来自新需求、旧清单中没有）"],
  "removed": ["被删除的功能点名称（旧清单中有、新需求不再需要）"],
  "modified": [
    {"name": "旧功能点名称", "from": "旧行为一句话", "to": "新行为一句话"}
  ],
  "unchanged": ["保持不变的功能点名称"],
  "note": "一句话说明变更要点"
}

## 规则
- modified 只收录**行为语义变化**的既有功能点（改名/调整交互/改数据来源等）；
  名称完全一致且行为未变的功能点放 unchanged
- added/removed 只做名称层面的增删判断（与既有清单逐项比对）
- 拿不准的放 unchanged，不要臆造"""


def _existing_feature_records(existing: list[Any]) -> list[dict]:
    """Normalize the existing-feature input to [{id, name}] records.

    Accepts feature dicts ({id, name}) and bare strings (name only).
    """
    records: list[dict] = []
    for f in existing or []:
        if isinstance(f, str) and f.strip():
            records.append({"id": "", "name": f.strip()})
        elif isinstance(f, dict):
            name = f.get("name") or f.get("title") or ""
            if name:
                records.append({"id": str(f.get("id") or ""), "name": str(name).strip()})
    return records


def _render_existing_features(records: list[dict]) -> str:
    lines = []
    for r in records:
        rid = f"（{r['id']}）" if r.get("id") else ""
        lines.append(f"- {r['name']}{rid}")
    return "\n".join(lines) or "（无已有功能点）"


def build_diff_user_prompt(existing: list[Any], new_requirement: str) -> str:
    records = _existing_feature_records(existing)
    return (
        f"## 已有功能点清单\n{_render_existing_features(records)}\n\n"
        f"## 用户新需求\n{new_requirement}\n\n"
        "请输出新增/删除/行为变更的功能点清单。"
    )


async def classify_diff(
    existing: list[Any],
    new_requirement: str,
    llm_fn: Any | None = None,
) -> dict:
    """8.1 diff — 新需求 vs 已有功能点: 确定性名称骨架 + LLM 行为变更分类.

    Returns ``{added, removed, removed_ids, modified, unchanged, note}``.
    ``removed_ids`` maps removed feature names back to their ids (when the
    existing records carry ids) — the test impact analysis keys retire off it.
    """
    from .brainstorm import parse_structured  # lazy: no module cycle
    from .memory import diff_requirement  # lazy: deterministic name skeleton

    records = _existing_feature_records(existing)
    base = {"features": [r["name"] for r in records]}
    det = diff_requirement(base, new_requirement)

    modified: list[dict] = []
    if llm_fn is not None:
        try:
            raw = await llm_fn(DIFF_SYSTEM_PROMPT, build_diff_user_prompt(existing, new_requirement))
            parsed = parse_structured(raw, DIFF_SCHEMA)
            modified = [
                m for m in (parsed.get("modified") or [])
                if isinstance(m, dict) and m.get("name")
            ]
        except Exception as e:  # noqa: BLE001 — fail-open: deterministic skeleton
            logger.warning("incremental_diff_llm_failed", error=str(e))

    name_to_id = {r["name"]: r["id"] for r in records if r.get("id")}
    removed_ids = [
        name_to_id[n] for n in det["removed"]
        if n in name_to_id
    ]

    diff = {
        "added": det["added"],
        "removed": det["removed"],
        "removed_ids": removed_ids,
        "modified": modified,
        "unchanged": det["unchanged"],
        "note": det["note"],
    }
    logger.info(
        "incremental_diff_done",
        added=len(diff["added"]), removed=len(diff["removed"]),
        modified=len(diff["modified"]),
    )
    return diff


# ── 8.2 Change manifest ──

MANIFEST_SCHEMA: dict = {
    "change_id": "",
    "type": "",
    "affected_modules": [""],
    "affected_requirement_points": [""],
    "behavior_changes": [{"point": "", "from": "", "to": ""}],
}

MANIFEST_SYSTEM_PROMPT = """你是增量开发架构师（Manager 判定角色）。基于功能点 diff 与用户新需求，判定本次变更并生成变更 manifest。

## 变更类型（type，只选一个）
- new_feature: 新增功能（不影响既有行为）
- behavior_change: 既有功能行为变更（交互/数据/流程变化）
- refactor: 重构（行为不变，只动实现）
- visual: 视觉改版（布局/样式，行为不变）

## 输出（只输出 JSON）
{
  "change_id": "占位，系统自动生成",
  "type": "behavior_change",
  "affected_modules": ["Header", "DataTable"],
  "affected_requirement_points": ["R-03"],
  "behavior_changes": [
    {"point": "R-03", "from": "客户端分页", "to": "服务端分页"}
  ]
}

## 规则
- affected_modules: 本次变更涉及的前端模块/组件名（kebab-case 或 PascalCase 文件/组件名）
- affected_requirement_points: 受影响的需求点 id（R-xx）；**只收录确实受影响的需求点**
- behavior_changes: 逐条记录行为变更（from 旧行为 → to 新行为）；行为未变的点不要写入
- new_feature/refactor/visual 类型：behavior_changes 原则上为空（重构/视觉不改变行为）
- 只输出 JSON"""


def build_manifest_user_prompt(
    state: GenerationState,
    diff: dict | None,
    requirements_summary: str = "",
) -> str:
    inc = state.get("incremental_context") or {}
    parts = [
        f"## 用户新需求\n{state.get('requirement', '')}",
    ]
    if diff:
        parts.append(
            "## 功能点 diff\n"
            + json.dumps(
                {k: v for k, v in diff.items() if k != "removed_ids"},
                ensure_ascii=False, indent=2,
            )
        )
    existing = requirements_summary or (inc.get("requirements") or "")
    if existing:
        parts.append(f"## 已有需求规格（摘要）\n{existing[:2000]}")
    parts.append("请生成本次变更的 manifest。")
    return "\n\n".join(parts)


def validate_manifest(manifest: dict) -> list[str]:
    """Schema check of a change manifest; returns error strings (empty = ok)."""
    errors: list[str] = []
    if not isinstance(manifest, dict):
        return ["manifest 不是对象"]
    mtype = manifest.get("type")
    if mtype not in MANIFEST_TYPES:
        errors.append(f"type 非法: {mtype!r}（∈ {MANIFEST_TYPES}）")
    for key in ("affected_modules", "affected_requirement_points"):
        value = manifest.get(key)
        if not isinstance(value, list):
            errors.append(f"{key} 非列表")
    bcs = manifest.get("behavior_changes")
    if not isinstance(bcs, list):
        errors.append("behavior_changes 非列表")
    elif any(not isinstance(b, dict) or not b.get("point") for b in bcs):
        errors.append("behavior_changes 存在缺 point 的条目")
    return errors


def build_change_id(project_root: str) -> str:
    """Deterministic change id ``chg-YYYY-MM-DD-NNN`` (NNN = seq within the day,
    derived from existing changes/ files — never reuses an id)."""
    seq = 0
    try:
        changes_dir = os.path.join(project_root, ".ai-memory", "changes")
        if os.path.isdir(changes_dir):
            for fn in os.listdir(changes_dir):
                m = re.fullmatch(r"chg-\d{4}-\d{2}-\d{2}-(\d+)\.json", fn)
                if m:
                    seq = max(seq, int(m.group(1)))
    except OSError:
        pass
    return f"chg-{time.strftime('%Y-%m-%d')}-{seq + 1:03d}"


async def generate_manifest(
    state: GenerationState,
    diff: dict | None = None,
    llm_fn: Any | None = None,
) -> dict:
    """8.2 变更 manifest — 结构化 LLM + schema 校验 + fail-safe.

    Returns the D9 manifest shape plus the Diagnoser-compatible derivations
    (``changed_requirements`` = behavior-changed points — NEVER the full
    affected list, so a new-feature manifest cannot mask a real regression;
    ``changes`` = per-change records with requirement_id).
    """
    from .brainstorm import _llm_structured  # lazy: nodes ↔ brainstorm cycle
    from .memory import project_root_for

    fn = llm_fn if llm_fn is not None else _default_llm
    project_root = project_root_for(state)
    change_id = build_change_id(project_root)

    inc = state.get("incremental_context") or {}
    parsed = await _llm_structured(
        MANIFEST_SYSTEM_PROMPT,
        build_manifest_user_prompt(state, diff, inc.get("requirements") or ""),
        MANIFEST_SCHEMA,
        fn,
    )

    mtype = parsed.get("type") if parsed.get("type") in MANIFEST_TYPES else DEFAULT_MANIFEST_TYPE
    manifest = {
        "change_id": change_id,
        "type": mtype,
        "affected_modules": [m for m in (parsed.get("affected_modules") or []) if m],
        "affected_requirement_points": [
            p for p in (parsed.get("affected_requirement_points") or []) if p
        ],
        "behavior_changes": [
            {"point": b.get("point", ""), "from": b.get("from", ""), "to": b.get("to", "")}
            for b in (parsed.get("behavior_changes") or [])
            if isinstance(b, dict) and b.get("point")
        ],
    }

    # 8.2 (review I4): 非行为变更类型 (new_feature/refactor/visual) 的
    # behavior_changes 一律确定性剔除 —— 行为不变, 不得让诊断器把回归当预期。
    if mtype != "behavior_change":
        manifest["behavior_changes"] = []

    manifest = derive_manifest_compat(manifest)

    errs = validate_manifest(manifest)
    if errs:
        logger.warning("incremental_manifest_invalid", errors=errs)
    logger.info(
        "incremental_manifest_generated",
        change_id=change_id, type=mtype, modules=len(manifest["affected_modules"]),
    )
    return manifest


def derive_manifest_compat(manifest: dict) -> dict:
    """Derive the Diagnoser-compatible fields onto the D9 manifest.

    ``changed_requirements`` = the *behavior*-changed points (raw ids, deduped,
    order-preserving) — NEVER the full affected list, so a refactor /
    new-feature manifest cannot mask a real regression (the Diagnoser's
    expected_broken classification keys off behavior changes).
    """
    behavior_points = list(dict.fromkeys(
        b["point"] for b in (manifest.get("behavior_changes") or [])
        if isinstance(b, dict) and b.get("point")
    ))
    if not behavior_points and manifest.get("type") == "behavior_change":
        behavior_points = list(dict.fromkeys(
            p for p in (manifest.get("affected_requirement_points") or []) if p
        ))
    manifest["changed_requirements"] = behavior_points
    manifest["changes"] = [
        {
            "requirement_id": b["point"],
            "point": b["point"],
            "from": b.get("from", ""),
            "to": b.get("to", ""),
        }
        for b in (manifest.get("behavior_changes") or [])
        if isinstance(b, dict) and b.get("point")
    ]
    return manifest


# ── 8.4 Test impact analysis ──


def _uses_fragile_selector(case: dict) -> bool:
    """True when the case targets elements via css/role selectors (selector
    heuristics — a refactor may silently break them)."""
    for step in case.get("steps") or []:
        if not isinstance(step, dict):
            continue
        target = step.get("target")
        if isinstance(target, dict) and target.get("by") in _FRAGILE_BY:
            return True
    return False


def analyze_test_impact(
    manifest: dict | None,
    existing_cases: list[dict],
    diff: dict | None = None,
) -> list[dict]:
    """8.4 Test Impact — 确定性 per-case 处置 (keep/update/retire/fix-selector).

    Rules (deterministic, in precedence order):
    - **retire**: requirement point in ``diff.removed_ids`` (需求点已删除);
    - **update**: point in ``affected_requirement_points`` — behavior changed,
      the case must be re-designed;
    - **fix-selector**: point affected AND manifest type == refactor AND the
      case uses css/role selectors (行为不变, 选择器可能失效);
    - **keep**: otherwise.
    """
    if not existing_cases:
        return []
    affected = {
        normalize_requirement_id(p)
        for p in ((manifest or {}).get("affected_requirement_points") or [])
    }
    removed_ids = {
        normalize_requirement_id(r)
        for r in ((diff or {}).get("removed_ids") or [])
    }
    mtype = (manifest or {}).get("type", DEFAULT_MANIFEST_TYPE)

    out: list[dict] = []
    for case in existing_cases:
        if not isinstance(case, dict) or not case.get("id"):
            continue
        cid = case["id"]
        rid = normalize_requirement_id(case.get("requirement_id", ""))
        if rid and rid in removed_ids:
            out.append({
                "case_id": cid,
                "requirement_id": case.get("requirement_id", ""),
                "disposition": DISP_RETIRE,
                "reason": f"需求点 {case.get('requirement_id')} 已从新需求中移除",
            })
        elif rid and rid in affected:
            if mtype == "refactor" and _uses_fragile_selector(case):
                out.append({
                    "case_id": cid,
                    "requirement_id": case.get("requirement_id", ""),
                    "disposition": DISP_FIX_SELECTOR,
                    "reason": (
                        f"重构（行为不变）且需求点 {case.get('requirement_id')} 受影响；"
                        "用例使用 css/role 选择器，回归前需核对选择器"
                    ),
                })
            else:
                out.append({
                    "case_id": cid,
                    "requirement_id": case.get("requirement_id", ""),
                    "disposition": DISP_UPDATE,
                    "reason": f"需求点 {case.get('requirement_id')} 行为变更，用例需重新设计",
                })
        else:
            out.append({
                "case_id": cid,
                "requirement_id": case.get("requirement_id", ""),
                "disposition": DISP_KEEP,
                "reason": "需求点未变更，用例保持",
            })
    return out


def apply_dispositions(project_root: str, dispositions: list[dict]) -> dict:
    """8.4 应用处置清单 → e2e/manifest.json 状态: retire → archived,
    update → expected_broken (保留在版本历史, 6.6), keep/fix-selector → active.
    """
    updates: dict[str, str] = {}
    for d in dispositions or []:
        cid = d.get("case_id")
        if not cid:
            continue
        if d.get("disposition") == DISP_RETIRE:
            updates[cid] = STATUS_ARCHIVED
        elif d.get("disposition") == DISP_UPDATE:
            updates[cid] = STATUS_EXPECTED_BROKEN
        elif d.get("disposition") in (DISP_KEEP, DISP_FIX_SELECTOR):
            updates[cid] = STATUS_ACTIVE
    result = update_case_statuses(project_root, updates)
    logger.info("incremental_dispositions_applied", updates=len(updates), result=result)
    return result


# ── 8.3 增量实现守卫: delta 任务确定性过滤 (review I3) ──


def _path_in_modules(path: str, modules: list[str]) -> bool:
    """启发式判定文件路径是否落在受影响模块内 (模块名匹配路径/文件名/无扩展名主干)."""
    norm = path.replace("\\", "/")
    base = os.path.basename(norm)
    stem = base.rsplit(".", 1)[0] if "." in base else base
    for m in modules:
        m_norm = m.replace("\\", "/")
        if m_norm in norm or m_norm == base or m_norm == stem:
            return True
    return False


def filter_delta_tasks(
    tasks: list[dict],
    existing_files: dict[str, str],
    affected_modules: list[str],
) -> list[dict]:
    """8.3 增量任务确定性硬约束 (review I3) — 提示词约束是软约束, 这里兜底:

    1. 剔除任务 files 中**已存在于文件清单且不在受影响模块内**的文件
       (防止 delta 任务误覆盖未受影响模块的存量文件);
    2. 跨任务重复文件去重 (后出现的剔除);
    3. 空文件任务剔除 + 依赖清理。
    若过滤后无任何任务存活, 回退为仅去重版本 (fail-open — 不因过度剔除
    而让流水线空转)。
    """
    if not tasks:
        return tasks
    modules = [m for m in (affected_modules or []) if m]
    seen: set[str] = set()
    stripped: list[dict] = []
    for task in tasks:
        task = dict(task)
        files: list[str] = []
        for f in task.get("files") or []:
            if f in seen:
                logger.warning("incremental_delta_duplicate_file_stripped", file=f, task=task.get("id"))
                continue
            if modules and f in existing_files and not _path_in_modules(f, modules):
                logger.warning(
                    "incremental_delta_existing_outside_modules_stripped",
                    file=f, task=task.get("id"),
                )
                continue
            seen.add(f)
            files.append(f)
        task["files"] = files
        stripped.append(task)

    dropped_ids = {t.get("id") for t in stripped if not t.get("files")}
    alive = [t for t in stripped if t.get("id") not in dropped_ids]
    for t in alive:
        t["deps"] = [d for d in (t.get("deps") or []) if d not in dropped_ids]
    if dropped_ids:
        logger.warning("incremental_delta_tasks_dropped", ids=sorted(str(i) for i in dropped_ids))

    if not alive:
        # 过度剔除 (如 fallback DAG 全量文件被剔除) → 回退为仅去重版本
        # (基于原始任务, 不剔除任何存量文件 — 宁可保守也不让流水线空转)。
        logger.warning("incremental_delta_filter_emptied_tasks", fallback="dedupe_only")
        seen2: set[str] = set()
        fallback: list[dict] = []
        for task in tasks:
            t = dict(task)
            files = []
            for f in t.get("files") or []:
                if f in seen2:
                    continue
                seen2.add(f)
                files.append(f)
            t["files"] = files
            fallback.append(t)
        return fallback
    return alive


# ── Loaders: existing cases + incremental context ──

_CASE_FILE_RE = re.compile(r"^[A-Za-z0-9_-]+\.json$")


def load_existing_cases(project_root: str) -> list[dict]:
    """Load the persisted E2E cases (e2e/cases/*.json), annotating each with
    its manifest status. Fail-open → [] on any error."""
    cases: list[dict] = []
    try:
        cases_dir = os.path.join(project_root, "e2e", "cases")
        if not os.path.isdir(cases_dir):
            return []
        statuses = load_e2e_manifest(project_root)
        for fn in sorted(os.listdir(cases_dir)):
            if not _CASE_FILE_RE.match(fn):
                continue
            try:
                with open(os.path.join(cases_dir, fn), encoding="utf-8") as f:
                    case = json.load(f)
                if isinstance(case, dict) and case.get("id"):
                    case["status"] = statuses.get(case["id"], STATUS_ACTIVE)
                    cases.append(case)
            except (OSError, json.JSONDecodeError):
                continue
    except OSError as e:
        logger.warning("incremental_cases_load_failed", project_root=project_root, error=str(e))
    return cases


def load_e2e_manifest(project_root: str) -> dict[str, str]:
    """e2e/manifest.json → {case_id: status} (fail-open → {})."""
    statuses: dict[str, str] = {}
    try:
        with open(os.path.join(project_root, "e2e", "manifest.json"), encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            for entry in data.get("cases") or []:
                if isinstance(entry, dict) and entry.get("id"):
                    statuses[entry["id"]] = entry.get("status", STATUS_ACTIVE)
    except (OSError, json.JSONDecodeError):
        pass
    return statuses


def load_incremental_context(project_root: str) -> dict:
    """8.1 加载已有应用记忆上下文 (fail-open).

    Returns ``{summary, requirements, requirements_size, spec,
    generated_files, e2e_cases, e2e_manifest, features}`` — ``features`` =
    existing feature names (the diff base), ``requirements`` = full
    requirements.md (delta PRD context), ``spec`` = existing architecture.json
    (merged-spec base), ``generated_files`` = existing code file inventory
    (planner delta context + full-project verifier base).
    """
    from .memory import (
        load_section,
        load_summary,
        scan_generated_files,
    )

    ctx: dict = {
        "summary": None,
        "requirements": "",
        "requirements_size": 0,
        "spec": None,
        "generated_files": {},
        "e2e_cases": [],
        "e2e_manifest": {},
        "features": [],
    }
    try:
        summary = load_summary(project_root)
        if summary:
            ctx["summary"] = summary
            # features 携带 id (state.json 有 id 时) — diff 的 removed_ids 依赖
            # id 映射 (retire 处置的判定键)。
            state_json = summary.get("state") or {}
            records = [
                {"id": str(f.get("id") or ""), "name": str(f.get("name") or "")}
                for f in (state_json.get("features") or [])
                if isinstance(f, dict) and f.get("name")
            ]
            ctx["features"] = records if records else (summary.get("features") or [])
        req = load_section(project_root, "spec/requirements.md") or ""
        ctx["requirements"] = req
        ctx["requirements_size"] = len(req)
    except Exception as e:  # noqa: BLE001 — fail-open
        logger.warning("incremental_context_summary_failed", error=str(e))
    try:
        from .memory import ARCHITECTURE_JSON_PATH

        spec = load_section(project_root, ARCHITECTURE_JSON_PATH)
        if spec:
            try:
                ctx["spec"] = json.loads(spec)
            except json.JSONDecodeError:
                ctx["spec"] = None
    except Exception as e:  # noqa: BLE001 — fail-open
        logger.warning("incremental_context_spec_failed", error=str(e))
    ctx["generated_files"] = scan_generated_files(project_root)
    ctx["e2e_cases"] = load_existing_cases(project_root)
    ctx["e2e_manifest"] = load_e2e_manifest(project_root)
    return ctx


# ── changes/ records (8.2 draft + 8.5/8.6 finalize) ──


def write_change_record(project_root: str, change_id: str, record: dict) -> str | None:
    """Write ``.ai-memory/changes/<change_id>.json`` (atomic, fail-open)."""
    from .memory import _write_json  # same-package writer

    record.setdefault("change_id", change_id)
    record.setdefault("updated_at", time.strftime("%Y-%m-%dT%H:%M:%S"))
    path = _write_json(project_root, os.path.join(".ai-memory", "changes", f"{change_id}.json"), record)
    if path:
        logger.info("incremental_change_record_written", change_id=change_id)
    return path


def read_change_record(project_root: str, change_id: str) -> dict | None:
    from .memory import _read_json  # same-package reader

    data = _read_json(project_root, os.path.join(".ai-memory", "changes", f"{change_id}.json"))
    return data if isinstance(data, dict) else None


# ── 8.5 Regression accounting ──

STATUS_BY_ID = "status"


def build_regression_accounting(
    state: GenerationState,
    results: list[dict],
    diagnosis: dict | None,
    dispositions: list[dict] | None,
    project_root: str,
) -> dict:
    """8.5 回归对账 — 按用例状态对账 (active 红 = 真回归; expected_broken 红 =
    预期; archived = 不执行).

    Returns ``{cases: [{case_id, status, disposition, result}], counts}`` where
    ``result`` ∈ passed | not_run | expected | real_regression |
    selector_coupled | skipped.
    """
    manifest_statuses = load_e2e_manifest(project_root)
    disp_by_id = {
        (d or {}).get("case_id"): (d or {}).get("disposition", DISP_KEEP)
        for d in (dispositions or [])
    }
    results_by_id = {r.get("case_id"): r for r in (results or [])}
    diag_by_id = {}
    for d in ((diagnosis or {}).get("diagnoses") or []):
        if isinstance(d, dict) and d.get("case_id"):
            diag_by_id[d["case_id"]] = d.get("classification", "")

    seen: set[str] = set()
    rows: list[dict] = []
    for case in state.get("e2e_test_cases") or []:
        if not isinstance(case, dict) or not case.get("id"):
            continue
        cid = case["id"]
        seen.add(cid)
        status = manifest_statuses.get(cid, case.get(STATUS_BY_ID, STATUS_ACTIVE))
        rows.append(_account_one(cid, status, disp_by_id.get(cid), results_by_id, diag_by_id))

    # Archived (retired) cases were not executed — report them as not_run.
    for d in dispositions or []:
        cid = (d or {}).get("case_id")
        if cid and cid not in seen:
            seen.add(cid)
            status = manifest_statuses.get(cid, STATUS_ARCHIVED)
            rows.append(_account_one(cid, status, d.get("disposition"), results_by_id, diag_by_id))

    counts: dict[str, int] = {}
    for row in rows:
        counts[row["result"]] = counts.get(row["result"], 0) + 1
    return {"cases": rows, "counts": counts}


def _account_one(
    cid: str,
    status: str,
    disposition: str | None,
    results_by_id: dict,
    diag_by_id: dict,
) -> dict:
    result = results_by_id.get(cid)
    if result is None or result.get("status") == "skipped_requires_browser":
        if result is None:
            out = "not_run"
        else:
            out = "skipped"
    elif result.get("passed", False):
        out = "passed"
    elif status == STATUS_EXPECTED_BROKEN:
        out = "expected"
    else:
        # 诊断分类作 tiebreak; 状态翻转失败时诊断仍可能是 expected_broken —
        # 映射为 expected (counts 不得泄漏诊断桶名)。
        out = diag_by_id.get(cid, "real_regression")
        if out == "expected_broken":
            out = "expected"
    return {
        "case_id": cid,
        "status": status,
        "disposition": disposition or DISP_KEEP,
        "result": out,
    }


def record_regression_results(
    project_root: str,
    change_id: str,
    state: GenerationState,
    results: list[dict],
    diagnosis: dict | None,
    dispositions: list[dict] | None,
    accounting: dict | None = None,
) -> None:
    """8.5 回归结果入 changes/<change_id>.json (fail-open)."""
    if not change_id:
        return
    try:
        if accounting is None:
            accounting = build_regression_accounting(
                state, results, diagnosis, dispositions, project_root
            )
        record = read_change_record(project_root, change_id) or {}
        record.setdefault("diff", state.get("incremental_diff"))
        record.setdefault("manifest", state.get("change_manifest"))
        record["regression"] = {
            "counts": accounting.get("counts", {}),
            "cases": accounting.get("cases", []),
            "ran_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        write_change_record(project_root, change_id, record)
    except Exception as e:  # noqa: BLE001 — fail-open
        logger.warning("incremental_regression_record_failed", change_id=change_id, error=str(e))


# ── 8.6 Memory update ──

def affected_file_list(state: GenerationState) -> list[dict]:
    """Files created/modified by this change (content-diff vs the loaded
    existing inventory)."""
    existing = ((state.get("incremental_context") or {}).get("generated_files")) or {}
    current = state.get("generated_files") or {}
    affected = []
    for path in sorted(current.keys()):
        if path not in existing or existing.get(path) != current[path]:
            affected.append({"path": path, "created": path not in existing})
    return affected


def finalize_incremental_change(
    state: GenerationState,
    project_root: str,
    change_id: str,
    *,
    e2e_verdict: str = "pass",
    e2e_reason: str = "",
) -> dict | None:
    """8.6 增量完成 — changes/ 记录定稿 + state.json 功能状态推进 +
    index.json 版本推进 (全部 fail-open)."""
    try:
        from .memory import update_index_revision, write_incremental_state
    except Exception:  # pragma: no cover - fail-open
        return None
    if not change_id:
        return None
    try:
        record = read_change_record(project_root, change_id) or {}
        record.setdefault("diff", state.get("incremental_diff"))
        record.setdefault("manifest", state.get("change_manifest"))
        record["status"] = "completed"
        record["affected_files"] = affected_file_list(state)
        record.setdefault("regression", {})
        record["verdict"] = {"node": "e2e", "decision": e2e_verdict, "reason": e2e_reason}
        record["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        write_change_record(project_root, change_id, record)
    except Exception as e:  # noqa: BLE001 — fail-open
        logger.warning("incremental_finalize_record_failed", change_id=change_id, error=str(e))
    try:
        write_incremental_state(project_root, state)
    except Exception as e:  # noqa: BLE001 — fail-open
        logger.warning("incremental_finalize_state_failed", change_id=change_id, error=str(e))
    try:
        update_index_revision(project_root, change_id)
    except Exception as e:  # noqa: BLE001 — fail-open
        logger.warning("incremental_finalize_index_failed", change_id=change_id, error=str(e))
    logger.info("incremental_change_finalized", change_id=change_id)
    return record
