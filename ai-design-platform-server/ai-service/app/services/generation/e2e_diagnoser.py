"""Test Diagnoser — 3-way classification of failed E2E cases (task group 6.4).

Failed cases are classified into three buckets, based on the change manifest
(``state.change_manifest`` — populated by task group U8; this module MUST work
with it absent) and the runner's evidence (DOM snapshot + console/network
errors):

- **expected_broken**（预期失效）— the case's requirement point is declared
  changed by the manifest; the assertion failure matches the declared behavior
  change. The case is rewritten/updated later; the manifest status flips to
  ``expected_broken``; no code rollback.
- **selector_coupled**（选择器耦合）— the element exists (visible in the DOM
  snapshot) but the case's selector can't find it (e.g. the data-testid hook
  is missing). Fix the hook / switch selector; no code rollback alone.
- **real_regression**（真回归）— user-visible behavior is actually broken and
  the manifest does not declare the change. This carries the evidence back to
  the code worker (the existing e2e-fail → code rollback path).

The classifier is deterministic (no LLM) with an optional ``llm_fn`` seam for
ambiguous cases; when the LLM is unavailable/ambiguous it fails closed to
``real_regression`` (a real regression must never be masked as benign).

Diagnosis outcome is stored in state as ``e2e_diagnosis`` and consumed by the
e2e L1 gate (``manager.run_l1_checks``) — only ``real_regression`` cases count
as failures, so expected_broken / selector_coupled failures do NOT trigger the
code rollback alone.
"""

from __future__ import annotations

from typing import Any

import structlog

from .state import GenerationState
from .e2e_designer import (
    STATUS_EXPECTED_BROKEN,
    normalize_requirement_id,
    update_case_statuses,
)

logger = structlog.get_logger()

# Classification buckets
EXPECTED_BROKEN = "expected_broken"
SELECTOR_COUPLED = "selector_coupled"
REAL_REGRESSION = "real_regression"

# Runner result status for skipped complex cases (6.7).
SKIPPED_REQUIRES_BROWSER = "skipped_requires_browser"


# ── Manifest access (U8 wires it; absent → default classification) ──

def _changed_requirement_ids(change_manifest: Any) -> set[str]:
    """The set of requirement ids the manifest declares behavior-changed.

    Tolerates both ``{"changed_requirements": [...]}`` and
    ``{"changes": [{"requirement_id": ...}]}`` shapes; absent → empty set.
    """
    if not change_manifest or not isinstance(change_manifest, dict):
        return set()
    ids: set[str] = set()
    raw = change_manifest.get("changed_requirements") or []
    if isinstance(raw, list):
        ids.update(str(r) for r in raw if r)
    for change in change_manifest.get("changes") or []:
        if isinstance(change, dict):
            rid = change.get("requirement_id") or change.get("id")
            if rid:
                ids.add(str(rid))
    return ids


# ── Selector-coupling heuristic (deterministic, evidence-based) ──

_ELEMENT_NOT_FOUND_MARKERS = (
    "element not found",
    "not found",
    "timeout",
    "timed out",
    "等待超时",
    "未找到",
    "定位失败",
    "无法定位",
)


def _is_not_found_error(error: str) -> bool:
    lowered = (error or "").lower()
    return any(m in lowered for m in _ELEMENT_NOT_FOUND_MARKERS)


def _snapshot_contains(snapshot: str, needle: str) -> bool:
    return bool(needle) and needle in (snapshot or "")


def _failed_step_target(case: dict, result: dict) -> dict | None:
    """The target of the step that failed.

    The runner embeds the failing target in the error text
    ("Element not found: testid=pagination-next", 'Assertion failed: expected
    "第 2 页" ...'); match each step's target value against the error and take
    the first hit. Falls back to the case's first step target when the error
    names none (defensive).
    """
    error = result.get("error") or ""
    steps = case.get("steps") or []
    for step in steps:
        if not isinstance(step, dict):
            continue
        target = step.get("target")
        if not isinstance(target, dict):
            continue
        value = str(target.get("value") or "")
        if value and value in error:
            return target
    for step in steps:
        if isinstance(step, dict):
            target = step.get("target")
            if isinstance(target, dict):
                return target
    return None


def _text_hints(case: dict) -> list[str]:
    """Text hints from the case's steps (assert targets with by=text) — used
    to prove the page visibly rendered in the DOM snapshot."""
    hints = []
    for step in case.get("steps") or []:
        target = step.get("target")
        if isinstance(target, dict) and target.get("by") == "text" and target.get("value"):
            hints.append(str(target["value"]))
    return hints


def _selector_coupled_heuristic(case: dict, result: dict) -> tuple[bool, str]:
    """DOM-snapshot heuristic: the element is visually there but the case's
    selector cannot find it.

    - testid: snapshot lacks ``data-testid="<value>"`` while a text hint from
      the case proves the page rendered (hook missing / renamed) → coupled.
      No text hint present → the page state may genuinely be broken → NOT
      coupled (falls through to real regression).
    - text: snapshot contains the text value but the lookup failed (text split
      across nodes / inside inputs) → coupled.
    - css/role: snapshot contains the value (role attribute or css id/class)
      but the lookup failed → coupled.
    """
    error = result.get("error") or ""
    if not _is_not_found_error(error):
        return False, ""
    evidence = result.get("evidence") or {}
    snapshot = evidence.get("dom_snapshot") or ""
    if not snapshot:
        return False, ""
    target = _failed_step_target(case, result)
    if not isinstance(target, dict):
        return False, ""
    by = target.get("by")
    value = target.get("value") or ""
    if not value:
        return False, ""
    if by == "testid":
        # Hook missing — but only coupled when the page visibly rendered
        # (a text hint from the case appears in the snapshot).
        if f'data-testid="{value}"' not in snapshot and any(
            _snapshot_contains(snapshot, h) for h in _text_hints(case)
        ):
            return True, (
                f"DOM 快照中页面已渲染（含文本线索），但缺少 data-testid 钩子 "
                f'"{value}"（选择器耦合：埋点缺失或钩子名变更）'
            )
        return False, ""
    if by == "text":
        if _snapshot_contains(snapshot, value):
            return True, (
                f"DOM 快照包含目标文本「{value}」，但文本定位失败"
                "（文本被拆分/动态渲染延迟/在输入框值中）"
            )
        return False, ""
    if by in ("role", "css"):
        if _snapshot_contains(snapshot, value):
            return True, (
                f"DOM 快照包含选择器线索「{value}」，但 {by} 定位失败"
                "（角色/类名/属性变更）"
            )
        return False, ""
    return False, ""


# ── Per-case classification ──

def classify_failure(
    case: dict,
    result: dict,
    change_manifest: Any = None,
) -> dict:
    """Classify one failed case into the 3-way taxonomy (deterministic).

    Returns ``{case_id, classification, reason, evidence_refs}``.
    """
    case_id = result.get("case_id") or case.get("id") or "?"
    evidence_refs = ["dom_snapshot", "console_errors", "network_errors"]
    if result.get("status") == SKIPPED_REQUIRES_BROWSER:
        return {
            "case_id": case_id,
            "classification": "skipped",
            "reason": "requires_browser：一期跳过，待人工/后端浏览器执行",
            "evidence_refs": [],
        }

    # (a) 预期失效 — manifest declares the requirement behavior changed.
    req_id = normalize_requirement_id(case.get("requirement_id", ""))
    changed = {
        normalize_requirement_id(r) for r in _changed_requirement_ids(change_manifest)
    }
    if req_id and req_id in changed:
        return {
            "case_id": case_id,
            "classification": EXPECTED_BROKEN,
            "reason": (
                f"manifest 声明需求点 {case.get('requirement_id')} 行为变更，"
                "该失败为预期失效（改用例/改写为新行为断言）"
            ),
            "evidence_refs": evidence_refs,
        }

    # (b) 选择器耦合 — element visible in the DOM snapshot but not locatable.
    coupled, why = _selector_coupled_heuristic(case, result)
    if coupled:
        return {
            "case_id": case_id,
            "classification": SELECTOR_COUPLED,
            "reason": why,
            "evidence_refs": evidence_refs,
        }

    # (c) 真回归 — user-visible behavior actually broken (no manifest match,
    # no selector-coupling evidence). Ambiguous assertion mismatches can be
    # arbitrated by the optional LLM in ``diagnose_failures``.
    return {
        "case_id": case_id,
        "classification": REAL_REGRESSION,
        "reason": (
            "断言失败且 manifest 未声明该需求点行为变更：判为真实回归，"
            "携带证据回功能实现节点修复"
        ),
        "evidence_refs": evidence_refs,
    }


def _is_assertion_mismatch(result: dict) -> bool:
    """Ambiguity marker: the failure was an assertion/content mismatch rather
    than an element-locating failure (only these are LLM-arbitrated)."""
    return not _is_not_found_error(result.get("error") or "")


async def _llm_arbitrate(case: dict, result: dict, llm_fn: Any) -> dict:
    """Optional LLM arbitration for ambiguous failures (fail-closed to real
    regression on any unexpected output)."""
    import json

    from .brainstorm import parse_structured

    prompt = (
        "你是 Test Diagnoser。以下 E2E 用例断言失败，请三方分类（只输出 JSON）：\n"
        f"用例：{json.dumps(case, ensure_ascii=False)}\n"
        f"结果：{json.dumps(result.get('error') or '', ensure_ascii=False)}\n"
        "分类 ∈ expected_broken（行为变更预期失效）| selector_coupled（选择器耦合）| "
        "real_regression（真回归）。\n"
        '输出：{"classification": "...", "reason": "一句话"}\n'
        "拿不准时判 real_regression。"
    )
    raw = await llm_fn(
        "你是 E2E 失败诊断器，只输出 JSON。",
        prompt,
    )
    parsed = parse_structured(raw, {"classification": "", "reason": ""})
    classification = parsed.get("classification")
    if classification not in (EXPECTED_BROKEN, SELECTOR_COUPLED, REAL_REGRESSION):
        classification = REAL_REGRESSION
    return {
        "case_id": result.get("case_id") or case.get("id") or "?",
        "classification": classification,
        "reason": parsed.get("reason") or "LLM 仲裁判定",
        "evidence_refs": ["dom_snapshot", "console_errors", "network_errors"],
    }


# ── Batch diagnosis ──

async def diagnose_failures(
    state: GenerationState,
    results: list[dict],
    project_root: str | None = None,
    llm_fn: Any | None = None,
) -> dict:
    """Diagnose all failed cases of a completed E2E run (async entry point).

    Returns ``{diagnoses, counts, rollback_case_ids, manifest_present,
    manifest_updates}``. ``rollback_case_ids`` = only real regressions — the
    code rollback path keys off this list. Expected-broken cases get their
    manifest status flipped to ``expected_broken`` (6.6: 保留在版本历史中).

    When ``llm_fn`` is provided, ambiguous failures (assertion mismatches with
    no manifest declaration and no selector-coupling evidence) are arbitrated
    by the LLM; its verdict wins unless it is unusable (fail-closed to the
    deterministic real-regression verdict). ``llm_fn`` defaults to the
    graph-path singleton ``_llm_generate`` (M4: same fallback as the manager
    L2 gate); tests inject a fake.
    """
    if llm_fn is None:
        from .nodes import _llm_generate  # lazy: diagnoser ↔ nodes

        llm_fn = _llm_generate

    cases_by_id = {
        c.get("id"): c for c in (state.get("e2e_test_cases") or [])
        if isinstance(c, dict) and c.get("id")
    }
    manifest = state.get("change_manifest")
    failed = [
        r for r in (results or [])
        if not r.get("passed", False) and r.get("status") != SKIPPED_REQUIRES_BROWSER
    ]
    diagnoses = []
    status_updates: dict[str, str] = {}
    for r in failed:
        case = cases_by_id.get(r.get("case_id")) or {}
        d = classify_failure(case, r, manifest)
        # Optional LLM arbitration for ambiguous assertion mismatches.
        if (
            llm_fn is not None
            and d["classification"] == REAL_REGRESSION
            and _is_assertion_mismatch(r)
        ):
            try:
                d = await _llm_arbitrate(case, r, llm_fn)
            except Exception as e:  # noqa: BLE001 — arbitration never crashes
                logger.warning("e2e_diagnoser_llm_failed", case_id=r.get("case_id"), error=str(e))
        diagnoses.append(d)
        if d["classification"] == EXPECTED_BROKEN and case.get("id"):
            status_updates[case["id"]] = STATUS_EXPECTED_BROKEN

    counts = {
        EXPECTED_BROKEN: sum(1 for d in diagnoses if d["classification"] == EXPECTED_BROKEN),
        SELECTOR_COUPLED: sum(1 for d in diagnoses if d["classification"] == SELECTOR_COUPLED),
        REAL_REGRESSION: sum(1 for d in diagnoses if d["classification"] == REAL_REGRESSION),
    }
    rollback_case_ids = [
        d["case_id"] for d in diagnoses if d["classification"] == REAL_REGRESSION
    ]

    manifest_updates: dict = {"updated": []}
    if status_updates and project_root:
        manifest_updates = update_case_statuses(project_root, status_updates)

    diagnosis = {
        "diagnoses": diagnoses,
        "counts": counts,
        "rollback_case_ids": rollback_case_ids,
        "manifest_present": bool(manifest),
        "manifest_updates": manifest_updates,
    }
    logger.info(
        "e2e_diagnoser_done",
        failed=len(failed),
        expected_broken=counts[EXPECTED_BROKEN],
        selector_coupled=counts[SELECTOR_COUPLED],
        real_regression=counts[REAL_REGRESSION],
    )
    return diagnosis
