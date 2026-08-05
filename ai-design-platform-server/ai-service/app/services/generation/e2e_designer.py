"""Test Designer — E2E coverage matrix + structured DSL case generation (task group 6).

The Designer turns the requirement-point list (PRD 结构化产物) into a
coverage matrix ("需求点 → 用例" mapping) plus machine-readable DSL cases:

- **Requirement points** come from the brainstorm-structured requirements
  (``requirements_state_json.features``) when present; otherwise they are
  parsed from the PRD's 功能模块 section; a single "R-01 核心功能" fallback
  keeps the gate from vacuously passing on an empty list.
- **DSL cases** are produced by one structured LLM call (``llm_fn`` seam,
  matching ``brainstorm._llm_structured`` / ``generate_architecture_spec``
  patterns). Each case is schema-validated (id/requirement_id/scenario/steps
  non-empty; actions ∈ click|input|assert|wait; target.by ∈
  testid|text|role|css); an invalid result is regenerated once with the
  validation errors fed back, then the still-invalid cases are dropped with a
  note — LLM garbage never blocks the flow; the coverage gate reports the gap.
- **Selector priority** is a prompt-level rule: testid → text → role → css
  (css 兜底), mirroring the cross-node data-testid convention (5.7).
- **Coverage gate (6.5)**: computed deterministically from the validated
  cases — every requirement point needs ≥1 case; gaps are surfaced in the
  ``coverage_matrix`` card payload.
- **Case storage (6.6)**: on completion, cases are written to
  ``<project_root>/e2e/cases/<id>.json`` + ``e2e/manifest.json`` (status
  active / expected_broken / archived), fail-open (log, never block).
- **requires_browser (6.7)**: annotated in the DSL; the runner skips them and
  the gate counts only executed cases.

The module is pure stdlib + structlog (no nodes import) so ``nodes`` /
``graph`` can import it without cycles.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

import structlog

from .state import GenerationState

logger = structlog.get_logger()

# ── DSL constants ──

VALID_ACTIONS = ("click", "input", "assert", "wait")
VALID_BY = ("testid", "text", "role", "css")
VALID_ASSERTIONS = ("contains", "equals", "exists")

# Case statuses (spec: 用例入库版本化) — written to e2e/manifest.json.
STATUS_ACTIVE = "active"
STATUS_EXPECTED_BROKEN = "expected_broken"
STATUS_ARCHIVED = "archived"

# Structured-LLM merge schema (parse_structured type-coercion, never crashes).
# List schemas carry one element shape; merge keeps schema keys and drops
# unknown ones (assertion/value defaults must be present so assert steps and
# wait values survive the coercion).
DESIGNER_SCHEMA: dict = {
    "cases": [{
        "id": "",
        "requirement_id": "",
        "scenario": "",
        "steps": [{
            "action": "",
            "target": {"by": "", "value": ""},
            "value": "",
            "assertion": "",
        }],
        "requires_browser": False,
    }],
    "coverage_matrix": {},
}

# ── Test Designer prompt (6.1/6.2: DSL + selector priority) ──

E2E_DSL_PROMPT = """你是一个资深 QA 测试工程师（Test Designer）。根据需求点清单与架构 Spec，生成 E2E 测试用例：覆盖矩阵 + 结构化 DSL 用例（JSON，不是 Markdown 自然语言）。

## 输入
- 需求点清单：每个需求点形如 {"id": "R-01", "name": "分页功能", "description": "..."}
- 架构 Spec（JSON）：pages / component_tree 提供页面与组件线索

## 输出格式（只输出一个 JSON 对象，不要 Markdown 包裹，不要注释）
{
  "cases": [
    {
      "id": "tc-r03-1",
      "requirement_id": "R-03",
      "scenario": "分页切换",
      "steps": [
        {"action": "click", "target": {"by": "testid", "value": "pagination-next"}},
        {"action": "assert", "target": {"by": "text", "value": "第 2 页"}, "assertion": "contains"}
      ],
      "requires_browser": false
    }
  ],
  "coverage_matrix": {"R-03": ["tc-r03-1"]}
}

## 规则
- 覆盖：每个需求点（R-xx）至少 1 个用例；用例 id 前缀 tc-r<序号>-<n>（如 tc-r03-1）
- 用例粒度：一个用例只验证一个场景；steps 3~8 条
- 动作：action ∈ click | input | assert | wait
  - assert 步骤必须带 assertion ∈ contains | equals | exists
  - wait 步骤可用 target 等待元素出现，或 value 为毫秒数
- 选择器优先级（重要）：testid → text → role → css
  - 有 data-testid 钩子（kebab-case，如 pagination-next）优先用 testid
  - 无钩子时用可见文本 text；再退 role；css 仅作兜底
- 复杂用例标注：多页面流转 / 登录态 / 文件上传 / 弹窗跨域等 iframe 沙箱无法执行的场景，标 "requires_browser": true
- 只输出需求点清单内出现的需求点对应的用例；不要发明新的需求点"""


# ── Requirement points extraction (6.1 输入) ──

_MODULE_HEADING = re.compile(r"^#{1,6}\s*[0-9.]*\s*功能模块", re.M)
# 无序（- / *）或有序（1. 2.）列表项；名称截断在 括号/冒号 处（review M5）
_BULLET = re.compile(r"^\s*(?:[-*]|\d+\.)\s+(?:\*\*)?([^*\n（(：:]+)", re.M)
# 任意级别标题（\n# ... ）都截断功能模块段（review M5）
_NEXT_HEADING = re.compile(r"\n#{1,6}\s")


def _clean_module_name(raw: str) -> str:
    """Truncate the module name at separators（/（/：/: and strip whitespace."""
    for sep in ("：", ":", "（", "("):
        idx = raw.find(sep)
        if idx != -1:
            raw = raw[:idx]
    return raw.strip()


def _parse_prd_modules(prd: str) -> list[dict]:
    """Parse the PRD 功能模块 section bullets into requirement points."""
    text = prd or ""
    m = _MODULE_HEADING.search(text)
    if m:
        section = text[m.end():]
        end = _NEXT_HEADING.search(section)
        if end:
            section = section[:end.start()]
        names = [_clean_module_name(b) for b in _BULLET.findall(section)]
    else:
        # fallback: any top-level bullet list (PRD may not use the exact heading)
        names = []
        for line in text.splitlines():
            b = _BULLET.match(line)
            if b:
                names.append(_clean_module_name(b.group(1)))
    points = []
    for i, name in enumerate(names, start=1):
        if not name:
            continue
        points.append({
            "id": f"R-{i:02d}",
            "name": name,
            "description": "",
            "source": "prd",
        })
    return points


def extract_requirement_points(state: GenerationState) -> list[dict]:
    """Build the requirement-point list (R-01…) from state.

    Priority: ``requirements_state_json.features`` (澄清结构化产物) →
    PRD 功能模块 section → single core-function fallback.
    """
    req_json = state.get("requirements_state_json")
    if req_json:
        try:
            data = json.loads(req_json)
        except (json.JSONDecodeError, TypeError):
            data = None
        if isinstance(data, dict):
            features = data.get("features")
            if isinstance(features, list) and features:
                points = []
                for i, f in enumerate(features, start=1):
                    if not isinstance(f, dict):
                        continue
                    name = f.get("name") or f.get("title") or ""
                    if not name:
                        continue
                    rid = f.get("id")
                    points.append({
                        "id": rid if rid else f"R-{i:02d}",
                        "name": name,
                        "description": f.get("description", ""),
                        "source": "features",
                    })
                if points:
                    return points

    points = _parse_prd_modules(state.get("analysis_result") or "")
    if points:
        return points

    return [{
        "id": "R-01",
        "name": "核心功能",
        "description": "PRD 主流程",
        "source": "fallback",
    }]


def normalize_requirement_id(rid: str) -> str:
    """Normalize requirement ids (R-1 vs R-01) for coverage matching (M9:
    single source — the Diagnoser imports this instead of re-implementing)."""
    if not rid:
        return ""
    m = re.match(r"^([A-Za-z]+)[-]?0*(\d+)$", str(rid).strip())
    if m:
        return f"{m.group(1).upper()}-{int(m.group(2))}"
    return str(rid).strip()


# ── DSL validation (6.1: schema check) ──

def validate_case(case: dict) -> list[str]:
    """Schema-validate one DSL case. Returns a list of error strings."""
    errors: list[str] = []
    if not isinstance(case, dict):
        return ["用例不是对象"]
    cid = case.get("id")
    if not cid or not isinstance(cid, str):
        errors.append("id 为空或非字符串")
    rid = case.get("requirement_id")
    if not rid or not isinstance(rid, str):
        errors.append("requirement_id 为空或非字符串")
    scenario = case.get("scenario")
    if not scenario or not isinstance(scenario, str):
        errors.append("scenario 为空或非字符串")
    steps = case.get("steps")
    if not isinstance(steps, list) or not steps:
        errors.append("steps 为空或非列表")
        return errors
    for i, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            errors.append(f"steps[{i}] 不是对象")
            continue
        action = step.get("action")
        if action not in VALID_ACTIONS:
            errors.append(f"steps[{i}] action 非法: {action!r}（∈ {VALID_ACTIONS}）")
        target = step.get("target")
        if action == "wait" and not isinstance(target, dict):
            # M1: wait 步骤允许无 target —— value 为毫秒数（与 prompt 一致）
            if not step.get("value"):
                errors.append(f"steps[{i}] wait 步骤需要 target 或 value（毫秒）")
        elif not isinstance(target, dict):
            errors.append(f"steps[{i}] target 不是 {{by, value}} 对象")
        else:
            by = target.get("by")
            value = target.get("value")
            if by not in VALID_BY:
                errors.append(f"steps[{i}] target.by 非法: {by!r}（∈ {VALID_BY}）")
            if not value or not isinstance(value, str):
                errors.append(f"steps[{i}] target.value 为空或非字符串")
        if action == "assert":
            assertion = step.get("assertion")
            if assertion not in VALID_ASSERTIONS:
                errors.append(
                    f"steps[{i}] assertion 非法: {assertion!r}（∈ {VALID_ASSERTIONS}）"
                )
    return errors


def _normalize_case(case: dict) -> dict:
    """Default-fill optional DSL fields (requires_browser / assertion)."""
    normalized = dict(case)
    normalized["requires_browser"] = bool(case.get("requires_browser"))
    steps = []
    for step in case.get("steps") or []:
        s = dict(step)
        if s.get("action") == "assert" and not s.get("assertion"):
            s["assertion"] = "contains"
        steps.append(s)
    normalized["steps"] = steps
    return normalized


# ── Coverage matrix (6.5 gate, deterministic) ──

def build_coverage_matrix(
    cases: list[dict],
    requirement_points: list[dict],
) -> dict:
    """Compute the coverage matrix + gate verdict from validated cases.

    Returns ``{rows, passed, gaps, total_requirements, covered_requirements,
    total_cases}``. ``passed`` is False when any requirement point has zero
    cases (coverage gate 6.5). Rows whose cases are ALL requires_browser get
    ``rb_only: True`` (M6) — covered at design time, but flagged: the in-phase
    runner skips them (6.7), so the manual-execution note must surface them.
    """
    by_req: dict[str, list[dict]] = {}
    for c in cases:
        rid = normalize_requirement_id(c.get("requirement_id", ""))
        if rid:
            by_req.setdefault(rid, []).append(c)
    rows = []
    for rp in requirement_points:
        rid = normalize_requirement_id(rp.get("id", ""))
        rcases = by_req.get(rid, [])
        rows.append({
            "requirement_id": rp.get("id", ""),
            "name": rp.get("name", ""),
            "case_ids": [c.get("id", "") for c in rcases],
            "covered": bool(rcases),
            "rb_only": bool(rcases) and all(
                c.get("requires_browser") for c in rcases
            ),
        })
    gaps = [r for r in rows if not r["covered"]]
    return {
        "rows": rows,
        "passed": not gaps,
        "gaps": gaps,
        "total_requirements": len(rows),
        "covered_requirements": len(rows) - len(gaps),
        "total_cases": len(cases),
    }


def coverage_card_payload(coverage: dict) -> dict:
    """The ``coverage_matrix`` card payload (matrix dict keyed by requirement id)."""
    matrix: dict[str, dict] = {}
    for row in coverage["rows"]:
        matrix[row["requirement_id"]] = {
            "name": row["name"],
            "case_ids": row["case_ids"],
            "covered": row["covered"],
            "rb_only": row["rb_only"],
        }
    return {
        "matrix": matrix,
        "passed": coverage["passed"],
        "gaps": [
            {"requirement_id": g["requirement_id"], "name": g["name"]}
            for g in coverage["gaps"]
        ],
        "total_requirements": coverage["total_requirements"],
        "covered_requirements": coverage["covered_requirements"],
        "total_cases": coverage["total_cases"],
    }


def coverage_card_content(coverage: dict) -> str:
    """Human-readable summary line for the coverage_matrix card."""
    lines = [
        f"覆盖矩阵：{coverage['covered_requirements']}/{coverage['total_requirements']} 个需求点已覆盖，"
        f"共 {coverage['total_cases']} 个用例",
    ]
    if coverage["passed"]:
        lines.append("全需求点已覆盖，矩阵通过，可进入用例确认环节。")
    else:
        gap_names = "、".join(
            f"{g['requirement_id']}（{g['name']}）" for g in coverage["gaps"]
        )
        lines.append(f"以下需求点无用例覆盖（矩阵未通过）：{gap_names}")
    rb_only = [r for r in coverage["rows"] if r["rb_only"]]
    if rb_only:
        names = "、".join(
            f"{r['requirement_id']}（{r['name']}）" for r in rb_only
        )
        lines.append(
            f"仅 requires_browser 用例覆盖（一期跳过，需人工执行）：{names}"
        )
    return "\n".join(lines)


# ── Rendered summary MD (frontend doc display compat) ──

def render_cases_md(
    cases: list[dict],
    coverage: dict,
    requirement_points: list[dict],
) -> str:
    """Render a Markdown summary of the DSL cases for the frontend doc view."""
    by_id = {rp.get("id"): rp.get("name", "") for rp in requirement_points}
    lines = ["# E2E 测试用例（结构化 DSL）", ""]
    lines.append("## 覆盖矩阵")
    lines.append(f"- 状态：{'通过' if coverage['passed'] else '未通过'}（{coverage['covered_requirements']}/{coverage['total_requirements']} 需求点覆盖，共 {coverage['total_cases']} 个用例）")
    for row in coverage["rows"]:
        mark = "✅" if row["covered"] else "❌ 未覆盖"
        cids = ", ".join(row["case_ids"]) or "（无用例）"
        lines.append(f"- {row['requirement_id']} {row['name']}：{mark} — {cids}")
    lines.append("")
    lines.append("## 用例清单")
    for c in cases:
        rid = c.get("requirement_id", "")
        name = by_id.get(rid, rid)
        rb = "（requires_browser：待人工执行）" if c.get("requires_browser") else ""
        lines.append(f"### {c.get('id', '?')} [{rid} {name}] {c.get('scenario', '')}{rb}")
        for step in c.get("steps") or []:
            target = step.get("target") or {}
            by = target.get("by", "")
            value = target.get("value", "")
            assertion = step.get("assertion")
            tail = f" ({assertion})" if assertion else ""
            lines.append(f"1. {step.get('action', '?')} {by}:{value}{tail}")
        lines.append("")
    return "\n".join(lines)


# ── Case storage (6.6: e2e/cases/*.json + manifest.json) ──

def project_root_for(state: GenerationState) -> str:
    """The generated-app project root — delegated to ``memory.project_root_for``
    (task group 7.1): persistent ``data/generated/<app_id>/`` replaces the old
    ``tempfile``-based root, single source for the whole pipeline."""
    from .memory import project_root_for as _project_root_for  # lazy: no module cycle

    return _project_root_for(state)


def _read_manifest(project_root: str) -> dict:
    path = os.path.join(project_root, "e2e", "manifest.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def write_cases_to_repo(
    project_root: str,
    cases: list[dict],
    coverage: dict | None = None,
) -> dict:
    """Write ``e2e/cases/<id>.json`` + ``e2e/manifest.json`` into project_root.

    Fail-open: write errors are logged and never block the pipeline. Existing
    manifest statuses (expected_broken / archived) are preserved across runs.
    Returns ``{written, case_paths, manifest_path}`` (or with ``error``).
    """
    result: dict = {"written": 0, "case_paths": [], "skipped": [], "manifest_path": None}
    try:
        e2e_dir = os.path.join(project_root, "e2e")
        cases_dir = os.path.join(e2e_dir, "cases")
        os.makedirs(cases_dir, exist_ok=True)
        old_manifest = _read_manifest(project_root)
        old_statuses: dict[str, str] = {}
        for entry in old_manifest.get("cases") or []:
            if isinstance(entry, dict) and entry.get("id"):
                old_statuses[entry["id"]] = entry.get("status", STATUS_ACTIVE)

        entries = []
        for c in cases:
            cid = c.get("id", "")
            if not cid:
                continue
            # M2 (review): case id doubles as a file name — refuse anything
            # outside [A-Za-z0-9_-] (path traversal guard), skip with a note.
            if not re.fullmatch(r"[A-Za-z0-9_-]+", cid):
                logger.warning("e2e_case_id_unsafe_skipped", case_id=cid)
                result["skipped"].append(cid)
                continue
            case_path = os.path.join(cases_dir, f"{cid}.json")
            with open(case_path, "w", encoding="utf-8") as f:
                json.dump(c, f, ensure_ascii=False, indent=2)
            result["case_paths"].append(case_path)
            result["written"] += 1
            status = old_statuses.get(cid, STATUS_ACTIVE)
            entries.append({
                "id": cid,
                "requirement_id": c.get("requirement_id", ""),
                "scenario": c.get("scenario", ""),
                "status": status,
                "requires_browser": bool(c.get("requires_browser")),
            })

        manifest = {
            "version": 1,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "cases": entries,
            "coverage": {
                "passed": bool((coverage or {}).get("passed", False)),
                "gaps": [
                    {"requirement_id": g["requirement_id"], "name": g["name"]}
                    for g in (coverage or {}).get("gaps", [])
                ],
            },
        }
        manifest_path = os.path.join(e2e_dir, "manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        result["manifest_path"] = manifest_path
        logger.info("e2e_cases_written", written=result["written"], manifest=manifest_path)
        return result
    except OSError as e:
        logger.warning("e2e_cases_write_failed", project_root=project_root, error=str(e))
        result["error"] = str(e)
        return result


def update_case_statuses(
    project_root: str,
    updates: dict[str, str],
) -> dict:
    """Update e2e/manifest.json statuses (e.g. expected_broken after diagnosis).

    Fail-open. Returns ``{updated: [case_id, ...]}`` or ``{"error": ...}``.
    """
    if not updates:
        return {"updated": []}
    try:
        manifest = _read_manifest(project_root)
        entries = manifest.get("cases") or []
        updated = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            cid = entry.get("id")
            if cid in updates and entry.get("status") != updates[cid]:
                entry["status"] = updates[cid]
                updated.append(cid)
        manifest["cases"] = entries
        manifest["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        path = os.path.join(project_root, "e2e", "manifest.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        logger.info("e2e_manifest_statuses_updated", updated=updated)
        return {"updated": updated}
    except OSError as e:
        logger.warning("e2e_manifest_update_failed", project_root=project_root, error=str(e))
        return {"error": str(e), "updated": []}


# ── Designer orchestration (6.1: LLM → validate → repair → drop) ──

def _default_llm(system_prompt: str, user_content: str) -> Any:
    """Default LLM seam (lazy import breaks the nodes ↔ designer cycle)."""
    from .nodes import _llm_generate  # lazy: nodes imports this module

    return _llm_generate(system_prompt, user_content)


async def run_e2e_designer(
    state: GenerationState,
    llm_fn: Any | None = None,
    project_root: str | None = None,
    max_attempts: int = 2,
    existing_cases: list[dict] | None = None,
) -> dict:
    """Run the Test Designer: points → LLM → coverage matrix + DSL cases.

    One structured LLM call; invalid cases trigger one regeneration with the
    validation errors fed back (same pattern as ``generate_architecture_spec``);
    still-invalid cases are dropped with a note (never block — the coverage
    gate reports the gap). Writes the cases into the repo and returns a full
    report consumed by ``e2e_node`` / graph event emission.

    ``existing_cases`` (8.3 regression mode): pre-existing cases that must be
    preserved verbatim (their ids are reserved; the LLM only ADDS cases for
    requirement points the preserved cases do not cover). Preserved cases are
    validated like new ones and merged into the final pool.

    Returns:
    ``{requirement_points, cases, coverage, dropped, errors, md, written,
    card_payload, card_content}``
    """
    from .brainstorm import _llm_structured  # lazy: nodes ↔ brainstorm cycle

    fn = llm_fn if llm_fn is not None else _default_llm
    points = extract_requirement_points(state)

    spec = state.get("architecture_spec")
    spec_block = (
        f"## 架构 Spec（JSON）\n{json.dumps(spec, ensure_ascii=False, indent=2)}"
        if spec
        else "## 架构 Spec\n（未提供）"
    )
    points_block = "\n".join(
        f'- {{"id": "{p["id"]}", "name": "{p["name"]}", "description": "{p.get("description", "")}"}}'
        for p in points
    )
    base_prompt = (
        f"## 需求点清单\n{points_block}\n\n{spec_block}\n\n"
        f"请生成覆盖矩阵与 DSL 用例（每个需求点至少 1 个用例）。"
    )

    # 8.3 regression mode: reserved preserved-case ids + prompt instruction.
    preserved_cases: list[dict] = []
    preserved_ids: set[str] = set()
    if existing_cases:
        preserved_cases = [
            _normalize_case(c) for c in existing_cases
            if isinstance(c, dict) and c.get("id")
        ]
        preserved_ids = {c["id"] for c in preserved_cases}
        if preserved_cases:
            preserved_block = "\n".join(
                f'- {c.get("id")} [{c.get("requirement_id", "")}] {c.get("scenario", "")}'
                for c in preserved_cases
            )
            base_prompt += (
                "\n\n## 既有用例（增量回归，必须原样保留 —— 禁止修改/删除/更换 id）\n"
                f"{preserved_block}\n\n"
                "只为未被上述既有用例覆盖的需求点生成新用例；既有用例 id 不得复用；"
                "新用例 id 从 tc-r<序号>-<n> 继续递增，避免与既有 id 冲突。"
            )

    pool: dict[str, dict] = {}
    for c in preserved_cases:
        pool[c["id"]] = c
    errors_by_case: dict[str, list[str]] = {}
    raw_errors: list[str] = []
    for attempt in range(max_attempts):
        user_prompt = base_prompt
        if attempt > 0 and errors_by_case:
            feedback_lines = []
            for cid, errs in errors_by_case.items():
                if errs:
                    feedback_lines.append(f"- {cid}: " + "；".join(errs))
            user_prompt += (
                "\n\n## 上一版用例未通过 schema 校验（必须全部修正，修正不了就删掉该用例）\n"
                + "\n".join(feedback_lines)
                + "\n\n请重新输出完整的 JSON（只输出 JSON 对象）。"
            )
        parsed = await _llm_structured(E2E_DSL_PROMPT, user_prompt, DESIGNER_SCHEMA, fn)
        candidate_cases = parsed.get("cases") or []
        candidate_cases = [
            _normalize_case(c) for c in candidate_cases if isinstance(c, dict)
        ]
        # M3 (review): merge — the retry output wins per case id, but
        # previously-valid cases the retry omitted are NOT lost (they persist
        # in the pool and are re-validated).
        for c in candidate_cases:
            cid = c.get("id", f"case-{len(pool)}")
            if cid in preserved_ids:
                # 8.3: preserved (incremental regression) ids are reserved —
                # a model that violates the id-reuse rule must not clobber the
                # preserved case.
                logger.warning("e2e_preserved_id_reuse_skipped", case_id=cid)
                continue
            pool[cid] = c
        cases = list(pool.values())
        errors_by_case = {
            c.get("id", f"case-{i}"): validate_case(c)
            for i, c in enumerate(cases)
        }
        invalid_ids = {cid for cid, errs in errors_by_case.items() if errs}
        if not invalid_ids:
            break
        logger.warning("e2e_dsl_validation_failed", attempt=attempt + 1, invalid=len(invalid_ids))

    # Final: keep valid cases, drop invalid ones with a note.
    valid: list[dict] = []
    dropped: list[dict] = []
    for c in cases:
        errs = errors_by_case.get(c.get("id", ""), [])
        if errs:
            dropped.append({"case": c, "errors": errs})
            raw_errors.extend(errs)
        else:
            valid.append(c)

    coverage = build_coverage_matrix(valid, points)
    md = render_cases_md(valid, coverage, points)

    written: dict = {}
    if project_root:
        written = write_cases_to_repo(project_root, valid, coverage)
        # 8.3 (review M2): 增量回归模式下, 新/重生成的用例 id 若复用了历史
        # 归档 (archived/expected_broken) id, 必须重置为 active —— 否则用例
        # 继承陈旧状态, 永远不参与执行。保留集 (keep/fix-selector) 状态不变。
        if existing_cases and valid:
            stale_ids = [
                c["id"] for c in valid
                if c.get("id") and c["id"] not in preserved_ids
            ]
            if stale_ids:
                update_case_statuses(
                    project_root, {cid: STATUS_ACTIVE for cid in stale_ids}
                )

    report = {
        "requirement_points": points,
        "cases": valid,
        "coverage": coverage,
        "dropped": dropped,
        "errors": raw_errors,
        "md": md,
        "written": written,
        "card_payload": coverage_card_payload(coverage),
        "card_content": coverage_card_content(coverage),
    }
    logger.info(
        "e2e_designer_done",
        points=len(points),
        cases=len(valid),
        dropped=len(dropped),
        coverage_passed=coverage["passed"],
    )
    return report
