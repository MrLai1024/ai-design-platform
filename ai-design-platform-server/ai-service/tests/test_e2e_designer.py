"""Tests for the Test Designer (task group 6.1/6.2/6.5/6.6/6.7).

Covers: requirement-point extraction (requirements_state_json features → PRD
模块 fallback → single fallback), DSL generation + schema validation/repair,
coverage-matrix gate (需求点无用例 → 未通过), selector-priority prompt rule,
case files + manifest writing (status fields), coverage card payload.
"""

import json
import os

import pytest

from app.services.generation.e2e_designer import (
    E2E_DSL_PROMPT,
    build_coverage_matrix,
    coverage_card_content,
    coverage_card_payload,
    extract_requirement_points,
    run_e2e_designer,
    update_case_statuses,
    validate_case,
    write_cases_to_repo,
)


def _state(**overrides) -> dict:
    state = {
        "requirement": "生成一个用户管理页面",
        "analysis_result": None,
        "requirements_state_json": None,
        "architecture_spec": None,
        "generated_files": {},
    }
    state.update(overrides)
    return state


# ── Requirement points extraction ──

def test_points_from_requirements_state_features():
    req_json = json.dumps({
        "features": [
            {"id": "f1", "name": "用户管理", "description": "增删改查"},
            {"name": "分页", "description": ""},
        ],
        "pages": [],
    }, ensure_ascii=False)
    points = extract_requirement_points(_state(requirements_state_json=req_json))
    assert points[0] == {"id": "f1", "name": "用户管理", "description": "增删改查", "source": "features"}
    assert points[1]["id"] == "R-02"
    assert points[1]["name"] == "分页"


def test_points_fallback_to_prd_modules():
    prd = (
        "# 需求规格文档\n\n## 2. 功能模块\n"
        "- 用户管理（必须有）\n"
        "- **分页功能**\n"
        "- 数据导出\n\n## 3. 页面结构\n- 用户列表页\n"
    )
    points = extract_requirement_points(_state(analysis_result=prd))
    assert [p["id"] for p in points] == ["R-01", "R-02", "R-03"]
    assert points[0]["name"] == "用户管理"
    assert points[1]["name"] == "分页功能"
    assert all(p["source"] == "prd" for p in points)


def test_points_prd_numbered_bullets_and_name_truncation():
    """M5: 有序列表项（1. 2.）、名称截断在 冒号/括号、任意级别标题截断段落。"""
    prd = (
        "# 需求规格文档\n\n"
        "## 功能模块\n"
        "1. 用户管理：增删改查\n"
        "2. 数据导出（必须有）\n"
        "3. 分页\n"
        "\n# 其它章节\n"
        "- 不应被解析的功能点\n"
    )
    points = extract_requirement_points(_state(analysis_result=prd))
    assert [p["name"] for p in points] == ["用户管理", "数据导出", "分页"]
    # `\n# 其它章节`（一级标题）必须截断功能模块段
    assert len(points) == 3


def test_points_single_fallback_when_no_source():
    points = extract_requirement_points(_state(analysis_result="没有功能模块"))
    assert len(points) == 1
    assert points[0]["id"] == "R-01"


# ── DSL validation ──

def _valid_case(**overrides) -> dict:
    case = {
        "id": "tc-r01-1",
        "requirement_id": "R-01",
        "scenario": "页面加载",
        "steps": [
            {"action": "click", "target": {"by": "testid", "value": "save-button"}},
            {"action": "assert", "target": {"by": "text", "value": "保存成功"},
             "assertion": "contains"},
        ],
        "requires_browser": False,
    }
    case.update(overrides)
    return case


def test_validate_case_ok():
    assert validate_case(_valid_case()) == []


def test_validate_case_rejects_bad_schema():
    assert validate_case({}) != []
    assert validate_case(_valid_case(id="")) != []
    assert validate_case(_valid_case(requirement_id="")) != []
    assert validate_case(_valid_case(scenario="")) != []
    assert validate_case(_valid_case(steps=[])) != []


def test_validate_case_rejects_bad_action_and_by():
    bad_action = _valid_case(steps=[
        {"action": "hover", "target": {"by": "testid", "value": "x"}},
    ])
    assert any("action" in e for e in validate_case(bad_action))
    bad_by = _valid_case(steps=[
        {"action": "click", "target": {"by": "xpath", "value": "//div"}},
    ])
    assert any("target.by" in e for e in validate_case(bad_by))


def test_validate_case_rejects_assert_without_assertion():
    case = _valid_case(steps=[
        {"action": "assert", "target": {"by": "text", "value": "你好"}},
    ])
    assert any("assertion" in e for e in validate_case(case))


def test_validate_case_wait_without_target_ok():
    """M1: wait 步骤允许无 target —— value 为毫秒数（与 prompt 一致）。"""
    case = _valid_case(steps=[
        {"action": "wait", "target": None, "value": "2000"},
    ])
    assert validate_case(case) == []
    # 无 target 也无 value → 非法
    case2 = _valid_case(steps=[
        {"action": "wait", "target": None, "value": None},
    ])
    assert any("wait" in e for e in validate_case(case2))


def test_selector_priority_in_prompt():
    """6.2: the TESTER prompt instructs selector priority testid → text → role → css."""
    assert "testid → text → role → css" in E2E_DSL_PROMPT
    # css is a fallback only
    assert "css" in E2E_DSL_PROMPT


# ── Designer LLM flow ──

def _designer_json(cases: list[dict]) -> str:
    return json.dumps({"cases": cases, "coverage_matrix": {}}, ensure_ascii=False)


@pytest.mark.asyncio
async def test_designer_valid_cases_coverage_passes():
    from unittest.mock import AsyncMock

    cases = [_valid_case()]
    llm = AsyncMock(return_value=_designer_json(cases))
    report = await run_e2e_designer(
        _state(analysis_result="# 需求\n## 2. 功能模块\n- 用户管理"),
        llm_fn=llm,
        project_root=None,
    )
    assert [c["id"] for c in report["cases"]] == ["tc-r01-1"]
    assert report["dropped"] == []
    assert report["coverage"]["passed"] is True
    assert report["coverage"]["covered_requirements"] == 1
    assert report["coverage"]["total_cases"] == 1
    # rendered summary MD for the frontend doc view
    assert "tc-r01-1" in report["md"]
    assert "保存成功" in report["md"]


@pytest.mark.asyncio
async def test_designer_coverage_gate_marks_gap():
    from unittest.mock import AsyncMock

    # R-01 covered, R-02 has no case → matrix not passed, gap reported
    llm = AsyncMock(return_value=_designer_json([_valid_case()]))
    report = await run_e2e_designer(
        _state(analysis_result="# 需求\n## 2. 功能模块\n- 用户管理\n- 数据导出"),
        llm_fn=llm,
        project_root=None,
    )
    assert report["coverage"]["passed"] is False
    assert report["coverage"]["gaps"][0]["requirement_id"] == "R-02"
    assert "R-02" in coverage_card_content(report["coverage"])
    payload = coverage_card_payload(report["coverage"])
    assert payload["passed"] is False
    assert payload["matrix"]["R-02"]["covered"] is False


@pytest.mark.asyncio
async def test_designer_invalid_cases_repair_then_drop():
    """6.1 非法 DSL: regenerate once with errors; still-invalid → dropped with note."""
    from unittest.mock import AsyncMock

    invalid = _valid_case(id="tc-bad", steps=[
        {"action": "fly", "target": {"by": "magic", "value": "x"}},
    ])
    llm = AsyncMock()
    # attempt 1: invalid JSON-schema case (bad action/by); attempt 2: fixed case
    llm.side_effect = [
        _designer_json([invalid]),
        _designer_json([_valid_case(), invalid]),
    ]
    report = await run_e2e_designer(
        _state(analysis_result="# 需求\n## 2. 功能模块\n- 用户管理"),
        llm_fn=llm,
        project_root=None,
    )
    assert llm.await_count == 2                    # regenerated once
    assert [c["id"] for c in report["cases"]] == ["tc-r01-1"]
    assert len(report["dropped"]) == 1             # tc-bad dropped with note
    assert report["dropped"][0]["errors"]
    # invalid case must not corrupt the coverage gate
    assert report["coverage"]["passed"] is True


@pytest.mark.asyncio
async def test_designer_retry_merges_previous_valid_cases():
    """M3: 重生成不丢已通过用例 —— 重试输出按 id 覆盖，未重发的有效用例保留。"""
    from unittest.mock import AsyncMock

    invalid = _valid_case(id="tc-bad", steps=[
        {"action": "fly", "target": {"by": "magic", "value": "x"}},
    ])
    llm = AsyncMock()
    # attempt 1: valid A + invalid B; attempt 2: LLM 只重发了 A（修好后漏发 B）
    llm.side_effect = [
        _designer_json([_valid_case(), invalid]),
        _designer_json([_valid_case()]),
    ]
    report = await run_e2e_designer(
        _state(analysis_result="# 需求\n## 2. 功能模块\n- 用户管理"),
        llm_fn=llm,
        project_root=None,
    )
    assert llm.await_count == 2
    # 之前有效的用例未被重试覆盖掉
    assert [c["id"] for c in report["cases"]] == ["tc-r01-1"]
    # 仍然非法的用例以 dropped + 错误说明保留（而不是静默丢失）
    assert [d["case"]["id"] for d in report["dropped"]] == ["tc-bad"]


@pytest.mark.asyncio
async def test_designer_invalid_json_fails_safe_to_empty():
    from unittest.mock import AsyncMock

    llm = AsyncMock(return_value="不是 JSON")
    report = await run_e2e_designer(
        _state(analysis_result="# 需求\n## 2. 功能模块\n- 用户管理"),
        llm_fn=llm,
        project_root=None,
    )
    assert report["cases"] == []
    assert report["coverage"]["passed"] is False  # gate reports the gap


@pytest.mark.asyncio
async def test_designer_rb_only_rows_flagged_in_coverage():
    """M6: 仅 requires_browser 用例覆盖的需求点 —— 矩阵行标记 rb_only，
    卡片内容提示人工执行（不静默跳过）。"""
    from unittest.mock import AsyncMock

    rb = _valid_case(id="tc-r02-1", requirement_id="R-02",
                     scenario="多页面流转", requires_browser=True)
    llm = AsyncMock(return_value=_designer_json([rb]))
    report = await run_e2e_designer(
        _state(analysis_result="# 需求\n## 2. 功能模块\n- 用户管理\n- 多页面流转"),
        llm_fn=llm,
        project_root=None,
    )
    rows = {r["requirement_id"]: r for r in report["coverage"]["rows"]}
    assert rows["R-01"]["rb_only"] is False          # 无用例
    assert rows["R-02"]["rb_only"] is True           # 仅 RB 用例
    assert "requires_browser" in coverage_card_content(report["coverage"])
    payload = coverage_card_payload(report["coverage"])
    assert payload["matrix"]["R-02"]["rb_only"] is True


@pytest.mark.asyncio
async def test_designer_requires_browser_annotation_survives():
    from unittest.mock import AsyncMock

    rb = _valid_case(id="tc-r99-1", requirement_id="R-99",
                     scenario="多页面流转", requires_browser=True)
    llm = AsyncMock(return_value=_designer_json([_valid_case(), rb]))
    report = await run_e2e_designer(
        _state(analysis_result="# 需求\n## 2. 功能模块\n- 用户管理"),
        llm_fn=llm,
        project_root=None,
    )
    by_id = {c["id"]: c for c in report["cases"]}
    assert by_id["tc-r99-1"]["requires_browser"] is True
    assert by_id["tc-r01-1"]["requires_browser"] is False
    assert "requires_browser" in report["md"]


# ── Case storage (6.6) ──

def _write_root(tmp_path) -> str:
    return str(tmp_path / "generated-app")


def test_write_cases_to_repo_creates_files_and_manifest(tmp_path):
    project_root = _write_root(tmp_path)
    cases = [
        _valid_case(),
        _valid_case(id="tc-r02-1", requirement_id="R-02", scenario="数据导出"),
    ]
    coverage = build_coverage_matrix(cases, [
        {"id": "R-01", "name": "用户管理"},
        {"id": "R-02", "name": "数据导出"},
    ])
    result = write_cases_to_repo(project_root, cases, coverage)

    assert result["written"] == 2
    assert os.path.exists(os.path.join(project_root, "e2e", "cases", "tc-r01-1.json"))
    with open(os.path.join(project_root, "e2e", "cases", "tc-r01-1.json"), encoding="utf-8") as f:
        assert json.load(f)["id"] == "tc-r01-1"

    manifest_path = os.path.join(project_root, "e2e", "manifest.json")
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)
    assert manifest["version"] == 1
    statuses = {e["id"]: e["status"] for e in manifest["cases"]}
    assert statuses == {"tc-r01-1": "active", "tc-r02-1": "active"}
    assert manifest["coverage"]["passed"] is True


def test_write_cases_to_repo_preserves_expected_broken_status(tmp_path):
    project_root = _write_root(tmp_path)
    case = _valid_case()
    write_cases_to_repo(project_root, [case], None)
    # mark expected_broken, then re-write → status preserved
    update_case_statuses(project_root, {"tc-r01-1": "expected_broken"})
    write_cases_to_repo(project_root, [case], None)
    with open(os.path.join(project_root, "e2e", "manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    assert manifest["cases"][0]["status"] == "expected_broken"


def test_write_cases_to_repo_fails_open(tmp_path):
    # project_root is a file → OSError on mkdir → error returned, no raise
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    result = write_cases_to_repo(str(blocker), [_valid_case()], None)
    assert result["written"] == 0
    assert "error" in result


def test_write_cases_to_repo_skips_unsafe_case_ids(tmp_path):
    """M2: 用例 id 作为文件名 —— 路径穿越防护（../ 等非法字符跳过）。"""
    project_root = str(tmp_path / "generated-app")
    evil = _valid_case(id="../../evil")
    result = write_cases_to_repo(project_root, [evil], None)
    assert result["written"] == 0
    assert result["skipped"] == ["../../evil"]
    # 仓库内不得出现越界文件
    assert not os.path.exists(os.path.join(project_root, "..", "evil.json"))
    cases_dir = os.path.join(project_root, "e2e", "cases")
    assert os.listdir(cases_dir) == [] if os.path.exists(cases_dir) else True
    # 恶意用例也不进 manifest
    with open(os.path.join(project_root, "e2e", "manifest.json"), encoding="utf-8") as f:
        assert json.load(f)["cases"] == []
