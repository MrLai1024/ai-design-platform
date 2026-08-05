"""Tests for the Test Diagnoser (task group 6.4): 3-way classification.

Covers: 预期失效 (manifest-declared behavior change), 选择器耦合 (element
visible in DOM snapshot but not locatable), 真回归 (real regression), manifest
absent → default classification, skipped requires_browser exclusion,
rollback_case_ids (only real regressions), manifest status update.
"""

import json

import pytest

from app.services.generation.e2e_diagnoser import (
    EXPECTED_BROKEN,
    REAL_REGRESSION,
    SELECTOR_COUPLED,
    SKIPPED_REQUIRES_BROWSER,
    classify_failure,
    diagnose_failures,
)

CASE = {
    "id": "tc-r01-1",
    "requirement_id": "R-01",
    "scenario": "分页切换",
    "steps": [
        {"action": "click", "target": {"by": "testid", "value": "pagination-next"}},
        {"action": "assert", "target": {"by": "text", "value": "第 2 页"},
         "assertion": "contains"},
    ],
}

MANIFEST = {
    "changed_requirements": ["R-01"],
    "changes": [{"requirement_id": "R-01", "description": "分页改为无限滚动"}],
}


def _result(case_id="tc-r01-1", passed=False, error="Element not found: pagination-next",
            status="failed", snapshot=""):
    return {
        "case_id": case_id,
        "passed": passed,
        "error": error,
        "status": status,
        "evidence": {"dom_snapshot": snapshot, "console_errors": [], "network_errors": []},
    }


def _state(**overrides) -> dict:
    state = {
        "e2e_test_cases": [CASE],
        "change_manifest": None,
        "requirement": "生成一个用户管理页面",
    }
    state.update(overrides)
    return state


# ── (a) 预期失效 ──

def test_expected_broken_when_manifest_declares_change():
    d = classify_failure(CASE, _result(error="Assertion failed"), MANIFEST)
    assert d["classification"] == EXPECTED_BROKEN
    assert "R-01" in d["reason"]


def test_expected_broken_with_changes_list_shape():
    manifest = {"changes": [{"id": "R-01", "description": "改版"}]}
    d = classify_failure(CASE, _result(), manifest)
    assert d["classification"] == EXPECTED_BROKEN


def test_manifest_absent_defaults_to_non_expected():
    d = classify_failure(CASE, _result(), None)
    assert d["classification"] != EXPECTED_BROKEN


def test_other_requirement_change_does_not_leak():
    manifest = {"changed_requirements": ["R-99"]}
    d = classify_failure(CASE, _result(), manifest)
    assert d["classification"] == REAL_REGRESSION


# ── (b) 选择器耦合 ──

def test_selector_coupled_when_testid_missing_but_element_visible():
    # DOM snapshot contains the element's text but not the data-testid hook
    snapshot = '<html><body><button>下一页</button><span>第 2 页</span></body></html>'
    d = classify_failure(CASE, _result(snapshot=snapshot), None)
    assert d["classification"] == SELECTOR_COUPLED
    assert "data-testid" in d["reason"]


def test_selector_coupled_when_text_found_but_lookup_failed():
    case = {**CASE, "steps": [
        {"action": "assert", "target": {"by": "text", "value": "第 2 页"},
         "assertion": "contains"},
    ]}
    snapshot = '<html><body><span>第 2 页</span></body></html>'
    d = classify_failure(case, _result(error="Element not found: 第 2 页", snapshot=snapshot), None)
    assert d["classification"] == SELECTOR_COUPLED


def test_not_found_without_element_evidence_is_real_regression():
    snapshot = '<html><body><div>空白页面</div></body></html>'
    d = classify_failure(CASE, _result(snapshot=snapshot), None)
    assert d["classification"] == REAL_REGRESSION


def test_assertion_mismatch_without_manifest_is_real_regression():
    d = classify_failure(
        CASE,
        _result(error='Assertion failed: expected "第 2 页" in "pagination-next"'),
        None,
    )
    assert d["classification"] == REAL_REGRESSION


def test_failing_step_parsed_from_error_text_for_later_steps():
    """I4: 失败步骤从错误文本解析 —— 首步 testid 定位成功、后续文本断言失败的
    用例按「失败的那一步」分析（text 在快照中 → 选择器耦合），而非回退到首步。"""
    case = {
        "id": "tc-r01-2",
        "requirement_id": "R-01",
        "scenario": "加载更多后分页文案",
        "steps": [
            {"action": "click", "target": {"by": "testid", "value": "load-more"}},
            {"action": "assert", "target": {"by": "text", "value": "第 2 页"},
             "assertion": "contains"},
        ],
    }
    snapshot = '<html><body><button data-testid="load-more">加载更多</button><span>第 2 页</span></body></html>'
    # 错误文本提到「第 2 页」（失败步骤 = assert 文本步骤）；快照含该文本 →
    # 选择器耦合；若错误未提及任何步骤目标则回退首步
    result = _result(error='Assertion failed: expected "第 2 页" not found in page', snapshot=snapshot)
    d = classify_failure(case, result, None)
    assert d["classification"] == SELECTOR_COUPLED


# ── skipped cases (6.7) ──

def test_skipped_requires_browser_classified_as_skipped():
    d = classify_failure(CASE, _result(status=SKIPPED_REQUIRES_BROWSER), None)
    assert d["classification"] == "skipped"


# ── Batch diagnosis ──

@pytest.mark.asyncio
async def test_diagnose_failures_rollback_only_real_regressions(tmp_path):
    state = _state(
        change_manifest={"changed_requirements": ["R-01"]},
        e2e_test_cases=[CASE, {**CASE, "id": "tc-r02-1", "requirement_id": "R-02"}],
    )
    results = [
        _result(case_id="tc-r01-1", error="Assertion failed"),          # expected_broken
        _result(case_id="tc-r02-1", snapshot="<div>空</div>"),           # real regression
        _result(case_id="tc-r03-1", status=SKIPPED_REQUIRES_BROWSER),    # skipped, unknown case
    ]
    project_root = str(tmp_path / "generated-app")
    # mirror the real flow: the Test Designer wrote the manifest at generation
    # time; the Diagnoser flips statuses on top of it.
    from app.services.generation.e2e_designer import write_cases_to_repo
    write_cases_to_repo(project_root, state["e2e_test_cases"], None)
    diag = await diagnose_failures(state, results, project_root=project_root)

    assert diag["manifest_present"] is True
    assert diag["counts"] == {EXPECTED_BROKEN: 1, SELECTOR_COUPLED: 0, REAL_REGRESSION: 1}
    assert diag["rollback_case_ids"] == ["tc-r02-1"]
    # expected_broken case → manifest status flipped (6.6 保留在版本历史中)
    assert diag["manifest_updates"]["updated"] == ["tc-r01-1"]
    with open(project_root + "/e2e/manifest.json", encoding="utf-8") as f:
        manifest = json.load(f)
    assert manifest["cases"][0]["status"] == "expected_broken"


@pytest.mark.asyncio
async def test_diagnose_failures_manifest_absent():
    state = _state(e2e_test_cases=[CASE])
    diag = await diagnose_failures(state, [_result()], project_root=None)
    assert diag["manifest_present"] is False
    assert diag["rollback_case_ids"] == ["tc-r01-1"]


@pytest.mark.asyncio
async def test_diagnose_failures_unknown_case_defaults_to_real_regression():
    state = _state(e2e_test_cases=[CASE])
    diag = await diagnose_failures(state, [_result(case_id="tc-ghost")], project_root=None)
    assert diag["rollback_case_ids"] == ["tc-ghost"]


@pytest.mark.asyncio
async def test_diagnose_failures_llm_arbitrates_ambiguous():
    from unittest.mock import AsyncMock

    # deterministic verdict: real regression; LLM arbitrates → expected_broken
    llm = AsyncMock(return_value=json.dumps(
        {"classification": EXPECTED_BROKEN, "reason": "接口改版，文案变更"},
        ensure_ascii=False,
    ))
    state = _state(e2e_test_cases=[CASE])
    results = [_result(error='Assertion failed: expected "第 2 页"')]
    diag = await diagnose_failures(state, results, project_root=None, llm_fn=llm)
    assert diag["rollback_case_ids"] == []
    assert diag["counts"][EXPECTED_BROKEN] == 1


@pytest.mark.asyncio
async def test_diagnose_failures_llm_failsafe_to_real_regression():
    from unittest.mock import AsyncMock

    llm = AsyncMock(return_value="garbage not json")
    state = _state(e2e_test_cases=[CASE])
    diag = await diagnose_failures(
        state, [_result(error='Assertion failed: expected "第 2 页"')],
        project_root=None, llm_fn=llm,
    )
    # LLM output unusable → fail closed to the deterministic verdict
    assert diag["rollback_case_ids"] == ["tc-r01-1"]
