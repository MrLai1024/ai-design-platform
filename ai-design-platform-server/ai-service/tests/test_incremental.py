"""Task group 8 tests — incremental development workflow.

Covers: diff classification (deterministic skeleton + LLM enrichment +
fail-safe), change manifest generation (schema validation, fail-safe type,
diagnoser-compatible derivations, deterministic change ids), test impact
analysis (retire/update/fix-selector/keep), disposition application to the
e2e manifest, regression accounting (active red = real regression,
expected_broken red = expected, archived = not run), changes/ records +
state.json progression + index revision, the graph incremental entry flow
(diff → manifest → dispositions, pause/resume per step), delta PRD framing,
merged-spec design prompt, delta planner prompt, regression-mode e2e designer
(preserved cases + id-reuse guard), and the Diagnoser consuming a REAL
manifest (integration).
"""

import asyncio
import json
import os

import pytest
from unittest.mock import AsyncMock, patch

from app.services.generation import incremental as inc
from app.services.generation.e2e_designer import (
    STATUS_ACTIVE,
    STATUS_ARCHIVED,
    STATUS_EXPECTED_BROKEN,
    write_cases_to_repo,
)
from app.services.generation.e2e_diagnoser import (
    EXPECTED_BROKEN,
    REAL_REGRESSION,
    classify_failure,
)

PRD = (
    "# 需求规格文档\n\n"
    "## 2. 功能模块\n- 用户管理\n- 订单管理\n\n"
    "## 3. 页面结构\n- 用户列表页\n"
)
MANIFEST_JSON = (
    '{"type": "behavior_change", "affected_modules": ["DataTable"], '
    '"affected_requirement_points": ["R-01"], '
    '"behavior_changes": [{"point": "R-01", "from": "客户端分页", "to": "服务端分页"}]}'
)


def _state(**overrides) -> dict:
    state = {
        "requirement": "新需求：\n- 订单管理\n- 用户管理",
        "generation_id": "gen-inc-1",
        "user_id": "test-user",
        "messages": [{"role": "user", "content": "新需求"}],
        "requirements_state_json": None,
        "analysis_result": None,
        "design_result": None,
        "architecture_spec": None,
        "code_result": None,
        "generated_files": {},
        "compile_errors": None,
        "manager_verdicts": [],
        "brainstorm_decisions": None,
        "brainstorm_assumptions": None,
        "planner_dag": None,
        "context_summary": None,
        "stage_phase": "generating",
    }
    state.update(overrides)
    return state


def _write_memory(tmp_path, monkeypatch, generation_id="gen-inc-1"):
    """Write an existing-app memory (features 用户管理) + e2e cases."""
    monkeypatch.setenv("AI_GEN_DATA_DIR", str(tmp_path))
    from app.services.generation import memory

    state = _state(generation_id=generation_id)
    root = memory.project_root_for(state)
    memory.write_requirements(root, PRD)
    memory.write_state(root, _state(requirements_state_json=json.dumps(
        {"features": [{"id": "F-01", "name": "用户管理"}]}
    )))
    memory.update_index(root, stage="analysis")
    memory.update_index(root, stage="design")
    memory.update_index(root, stage="code")
    os.makedirs(os.path.join(root, "src"), exist_ok=True)
    with open(os.path.join(root, "src/App.vue"), "w", encoding="utf-8") as f:
        f.write("<template><div/></template>")
    # e2e: one active case for R-01 (分页) + one for R-03 (已移除点, retire 目标)
    cases = [
        {
            "id": "tc-r01-1",
            "requirement_id": "R-01",
            "scenario": "分页切换",
            "steps": [
                {"action": "click", "target": {"by": "testid", "value": "pagination-next"}},
                {"action": "assert", "target": {"by": "text", "value": "第 2 页"}, "assertion": "contains"},
            ],
        },
        {
            "id": "tc-r03-1",
            "requirement_id": "R-03",
            "scenario": "旧功能",
            "steps": [{"action": "assert", "target": {"by": "text", "value": "旧"}, "assertion": "contains"}],
        },
    ]
    write_cases_to_repo(root, cases)
    return root


# ── 8.1 diff classification ──


@pytest.mark.asyncio
async def test_classify_diff_deterministic_skeleton():
    existing = [{"id": "R-01", "name": "用户管理"}, {"id": "R-02", "name": "订单管理"}]
    diff = await inc.classify_diff(existing, "新需求：\n- 订单管理\n- 用户管理", llm_fn=None)
    assert diff["added"] == []
    assert diff["removed"] == []
    assert sorted(diff["unchanged"]) == ["用户管理", "订单管理"]
    assert diff["modified"] == []
    assert diff["removed_ids"] == []


@pytest.mark.asyncio
async def test_classify_diff_added_removed_and_removed_ids():
    existing = [{"id": "R-01", "name": "用户管理"}, {"id": "R-02", "name": "库存管理"}]
    diff = await inc.classify_diff(existing, "新需求：\n- 订单管理\n- 用户管理", llm_fn=None)
    assert diff["added"] == ["订单管理"]
    assert diff["removed"] == ["库存管理"]
    assert diff["removed_ids"] == ["R-02"]
    assert diff["unchanged"] == ["用户管理"]


@pytest.mark.asyncio
async def test_classify_diff_llm_modified_enrichment():
    existing = [{"id": "R-01", "name": "分页功能"}]
    new_req = "新需求：分页改为服务端分页"

    async def fake_llm(system_prompt, user_prompt):
        return json.dumps({
            "added": [],
            "removed": [],
            "modified": [{"name": "分页功能", "from": "客户端分页", "to": "服务端分页"}],
            "unchanged": [],
            "note": "分页行为变更",
        })

    diff = await inc.classify_diff(existing, new_req, llm_fn=fake_llm)
    assert len(diff["modified"]) == 1
    assert diff["modified"][0]["to"] == "服务端分页"


@pytest.mark.asyncio
async def test_classify_diff_fail_safe_on_llm_garbage():
    existing = [{"id": "R-01", "name": "分页功能"}]

    async def garbage_llm(system_prompt, user_prompt):
        return "not json at all"

    diff = await inc.classify_diff(existing, "新需求：\n- 订单管理", llm_fn=garbage_llm)
    assert diff["added"] == ["订单管理"]       # 确定性骨架仍然正确
    assert diff["modified"] == []


# ── 8.2 change manifest ──


@pytest.mark.asyncio
async def test_generate_manifest_schema_and_diagnoser_compat(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_GEN_DATA_DIR", str(tmp_path))

    async def fake_llm(system_prompt, user_prompt):
        return MANIFEST_JSON

    state = _state(requirement="分页改为服务端分页")
    manifest = await inc.generate_manifest(state, diff={"added": [], "removed": [], "modified": []}, llm_fn=fake_llm)
    assert manifest["type"] == "behavior_change"
    assert manifest["affected_modules"] == ["DataTable"]
    assert manifest["affected_requirement_points"] == ["R-01"]
    assert manifest["behavior_changes"][0]["to"] == "服务端分页"
    assert manifest["change_id"].startswith("chg-")
    # Diagnoser-compatible derivations
    assert manifest["changed_requirements"] == ["R-01"]
    assert manifest["changes"][0]["requirement_id"] == "R-01"
    assert inc.validate_manifest(manifest) == []


@pytest.mark.asyncio
async def test_generate_manifest_fail_safe_default_type(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_GEN_DATA_DIR", str(tmp_path))

    async def fake_llm(system_prompt, user_prompt):
        return '{"type": "bogus_type", "affected_modules": ["X"]}'

    state = _state()
    manifest = await inc.generate_manifest(state, diff=None, llm_fn=fake_llm)
    assert manifest["type"] == "new_feature"
    assert manifest["changed_requirements"] == []  # 无行为变更 → 不遮蔽真回归


def test_generate_manifest_new_feature_does_not_mask_regressions():
    manifest = inc.derive_manifest_compat({
        "type": "new_feature",
        "affected_requirement_points": ["R-05"],
        "behavior_changes": [],
    })
    assert manifest["changed_requirements"] == []
    manifest2 = inc.derive_manifest_compat({
        "type": "refactor",
        "affected_requirement_points": ["R-01"],
        "behavior_changes": [],
    })
    assert manifest2["changed_requirements"] == []


def test_build_change_id_sequence_increments(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_GEN_DATA_DIR", str(tmp_path))
    root = os.path.join(str(tmp_path), "generated", "gen-inc-1")
    os.makedirs(os.path.join(root, ".ai-memory", "changes"), exist_ok=True)
    cid1 = inc.build_change_id(root)
    assert cid1.endswith("-001")
    with open(os.path.join(root, ".ai-memory", "changes", f"{cid1}.json"), "w", encoding="utf-8") as f:
        json.dump({"change_id": cid1}, f)
    assert inc.build_change_id(root).endswith("-002")


# ── 8.4 test impact analysis ──


CASE_CSS = {
    "id": "tc-r01-2",
    "requirement_id": "R-01",
    "scenario": "分页切换",
    "steps": [{"action": "click", "target": {"by": "css", "value": ".pagination"}}],
}
CASE_R02 = {
    "id": "tc-r02-1",
    "requirement_id": "R-02",
    "scenario": "订单列表",
    "steps": [{"action": "assert", "target": {"by": "text", "value": "订单"}, "assertion": "contains"}],
}


def test_analyze_test_impact_dispositions():
    manifest = {
        "type": "behavior_change",
        "affected_requirement_points": ["R-01"],
        "behavior_changes": [{"point": "R-01", "from": "a", "to": "b"}],
    }
    diff = {"removed_ids": ["R-03"]}
    cases = [
        {"id": "tc-r01-1", "requirement_id": "R-01", "steps": []},   # affected → update
        CASE_CSS,                                                     # affected + css → update (非重构)
        CASE_R02,                                                     # 未受影响 → keep
        {"id": "tc-r03-1", "requirement_id": "R-03", "steps": []},   # removed → retire
    ]
    disp = {d["case_id"]: d for d in inc.analyze_test_impact(manifest, cases, diff)}
    assert disp["tc-r01-1"]["disposition"] == "update"
    assert disp["tc-r01-2"]["disposition"] == "update"
    assert disp["tc-r02-1"]["disposition"] == "keep"
    assert disp["tc-r03-1"]["disposition"] == "retire"


def test_analyze_test_impact_refactor_fix_selector():
    manifest = {"type": "refactor", "affected_requirement_points": ["R-01"], "behavior_changes": []}
    cases = [CASE_CSS, {"id": "tc-r01-1", "requirement_id": "R-01", "steps": []}]
    disp = {d["case_id"]: d for d in inc.analyze_test_impact(manifest, cases)}
    assert disp["tc-r01-2"]["disposition"] == "fix-selector"  # 重构 + css 选择器
    assert disp["tc-r01-1"]["disposition"] == "update"        # 重构 + testid → update


def test_analyze_test_impact_empty_cases():
    assert inc.analyze_test_impact({"type": "refactor"}, []) == []


def test_apply_dispositions_updates_manifest_statuses(tmp_path, monkeypatch):
    root = _write_memory(tmp_path, monkeypatch)
    cases = inc.load_existing_cases(root)
    assert cases and cases[0]["id"] == "tc-r01-1"
    dispositions = [
        {"case_id": "tc-r01-1", "disposition": "update", "reason": "行为变更"},
        {"case_id": "tc-r03-1", "disposition": "retire", "reason": "已移除"},
    ]
    inc.apply_dispositions(root, dispositions)
    statuses = inc.load_e2e_manifest(root)
    assert statuses["tc-r01-1"] == STATUS_EXPECTED_BROKEN
    assert statuses["tc-r03-1"] == STATUS_ARCHIVED


# ── 8.5 regression accounting ──


def _run_state(root, cases):
    from app.services.generation import memory

    memory.write_requirements(root, PRD)
    return _state(e2e_test_cases=cases, generated_files={"src/App.vue": "x"})


def test_regression_accounting_semantics(tmp_path, monkeypatch):
    root = _write_memory(tmp_path, monkeypatch)
    # statuses: tc-r01-1 active, tc-r01-2 expected_broken, tc-r03-1 archived
    cases = [
        {"id": "tc-r01-1", "requirement_id": "R-01", "steps": []},
        {"id": "tc-r01-2", "requirement_id": "R-01", "steps": []},
        {"id": "tc-r03-1", "requirement_id": "R-03", "steps": []},
    ]
    write_cases_to_repo(root, cases)
    inc.apply_dispositions(root, [
        {"case_id": "tc-r01-2", "disposition": "update"},
        {"case_id": "tc-r03-1", "disposition": "retire"},
    ])
    results = [
        {"case_id": "tc-r01-1", "passed": False, "status": "failed", "error": "assert failed"},
        {"case_id": "tc-r01-2", "passed": False, "status": "failed", "error": "assert failed"},
    ]
    diagnosis = {"diagnoses": [
        {"case_id": "tc-r01-1", "classification": REAL_REGRESSION, "reason": ""},
        {"case_id": "tc-r01-2", "classification": EXPECTED_BROKEN, "reason": ""},
    ]}
    state = _run_state(root, cases)
    accounting = inc.build_regression_accounting(
        state, results, diagnosis,
        [{"case_id": "tc-r01-2", "disposition": "update"},
         {"case_id": "tc-r03-1", "disposition": "retire"}],
        root,
    )
    rows = {r["case_id"]: r for r in accounting["cases"]}
    # active 红 → 真回归
    assert rows["tc-r01-1"]["result"] == REAL_REGRESSION
    assert rows["tc-r01-1"]["status"] == STATUS_ACTIVE
    # expected_broken 红 → 预期 (不触发回滚)
    assert rows["tc-r01-2"]["result"] == "expected"
    assert rows["tc-r01-2"]["status"] == STATUS_EXPECTED_BROKEN
    # archived → 不执行
    assert rows["tc-r03-1"]["result"] == "not_run"
    assert rows["tc-r03-1"]["status"] == STATUS_ARCHIVED
    assert accounting["counts"]["real_regression"] == 1
    assert accounting["counts"]["expected"] == 1


def test_regression_accounting_passed_cases():
    state = _state(e2e_test_cases=[{"id": "tc-r01-1", "requirement_id": "R-01", "steps": []}])
    results = [{"case_id": "tc-r01-1", "passed": True, "status": "passed"}]
    accounting = inc.build_regression_accounting(state, results, None, [], "/nonexistent")
    assert accounting["cases"][0]["result"] == "passed"


# ── changes/ records + finalize (8.2/8.5/8.6) ──


def test_change_record_write_and_finalize(tmp_path, monkeypatch):
    root = _write_memory(tmp_path, monkeypatch)
    change_id = "chg-2026-08-05-001"
    record = {"status": "draft", "diff": {"added": ["订单管理"]}, "manifest": {"change_id": change_id, "type": "behavior_change"}}
    assert inc.write_change_record(root, change_id, record)
    assert inc.read_change_record(root, change_id)["status"] == "draft"

    state = _state(
        incremental_context={
            "generated_files": {"src/App.vue": "<template><div/></template>"},
            "e2e_cases": [],
        },
        generated_files={
            "src/App.vue": "<template><div/></template>",
            "src/OrderTable.vue": "<template>order</template>",
        },
        requirements_state_json=json.dumps({
            "features": [{"id": "F-01", "name": "用户管理"}, {"id": "F-02", "name": "订单管理"}],
        }),
    )
    final = inc.finalize_incremental_change(state, root, change_id, e2e_verdict="pass")
    assert final is not None
    assert final["status"] == "completed"
    assert any(f["path"] == "src/OrderTable.vue" and f["created"] for f in final["affected_files"])
    assert final["verdict"]["decision"] == "pass"

    # state.json 功能状态推进: 新增 F-02 保留, F-01 历史保留
    from app.services.generation import memory

    state_json = memory._read_json(root, memory.STATE_JSON_PATH)
    ids = {f["id"] for f in state_json["features"]}
    assert "F-01" in ids and "F-02" in ids
    assert state_json["milestones"]["incremental_revisions"] == 1

    # index.json 版本推进
    index = memory.read_index(root)
    assert index["change_revision"] == 1
    assert index["last_change_id"] == change_id


# ── e2e_diagnoser 消费真实 manifest (integration) ──


@pytest.mark.asyncio
async def test_e2e_diagnoser_consumes_real_manifest(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_GEN_DATA_DIR", str(tmp_path))

    async def fake_llm(system_prompt, user_prompt):
        return MANIFEST_JSON

    state = _state(requirement="分页改为服务端分页")
    manifest = await inc.generate_manifest(state, diff=None, llm_fn=fake_llm)
    case = {"id": "tc-r01-1", "requirement_id": "R-01", "steps": []}
    d = classify_failure(case, {"case_id": "tc-r01-1", "passed": False, "error": "assert failed"}, manifest)
    assert d["classification"] == EXPECTED_BROKEN  # manifest 声明的行为变更 → 预期失效
    other = classify_failure(
        {"id": "tc-r02-1", "requirement_id": "R-02", "steps": []},
        {"case_id": "tc-r02-1", "passed": False, "error": "assert failed"}, manifest,
    )
    assert other["classification"] == REAL_REGRESSION  # 未声明 → 真回归


# ── graph 增量入口: diff → manifest → 处置 → 增量流水线 ──


@pytest.mark.asyncio
async def test_graph_incremental_diff_confirm_pauses(tmp_path, monkeypatch):
    from app.services.generation.graph import GraphRunner

    root = _write_memory(tmp_path, monkeypatch, generation_id="gen-inc-flow")
    state = _state(generation_id="gen-inc-flow", requirement="新需求：\n- 订单管理\n- 用户管理")
    state["incremental_mode"] = True
    runner = GraphRunner()
    events = [ev async for ev in runner.run(state, "gen-inc-flow")]
    types = [e["event_type"] for e in events]
    assert "prd_generate_start" not in types                     # 停在 diff 确认
    assert "human_confirm_required" in types
    cards = [e for e in events if e["event_type"] == "manager_message"]
    assert any("增量变更清单" in (e["data"].get("content") or "") for e in cards)
    assert state.get("incremental_diff") is not None
    assert state.get("incremental_context") is not None
    assert state["incremental_context"]["requirements"] == PRD
    assert state["incremental_diff"]["added"] == ["订单管理"]


@pytest.mark.asyncio
async def test_graph_incremental_manifest_step_after_diff(tmp_path, monkeypatch):
    from app.services.generation.graph import GraphRunner

    root = _write_memory(tmp_path, monkeypatch, generation_id="gen-inc-manifest")
    state = _state(generation_id="gen-inc-manifest", requirement="分页改为服务端分页")
    state["incremental_mode"] = True
    state["incremental_diff"] = {"added": [], "removed": [], "modified": [], "unchanged": [], "removed_ids": []}
    state["incremental_context"] = {
        "requirements": PRD, "requirements_size": len(PRD),
        "spec": None, "generated_files": {}, "e2e_cases": [], "e2e_manifest": {}, "features": [],
    }

    async def fake_llm(system_prompt, user_content, **kwargs):
        if "变更 manifest" in system_prompt:
            return MANIFEST_JSON
        return PRD

    runner = GraphRunner()
    with patch("app.services.generation.nodes._llm_generate", new_callable=AsyncMock, side_effect=fake_llm):
        events = [ev async for ev in runner.run(state, "gen-inc-manifest")]
    cards = [e for e in events if e["event_type"] == "manager_message"]
    assert any("变更 manifest" in (e["data"].get("content") or "") for e in cards)
    assert any("涉及模块" in (e["data"].get("content") or "") for e in cards)
    assert "human_confirm_required" in [e["event_type"] for e in events]
    assert state.get("change_manifest") is not None
    assert state["change_manifest"]["type"] == "behavior_change"
    # 草稿记录已写入 changes/
    record = inc.read_change_record(root, state["change_id"])
    assert record is not None and record["status"] == "draft"


@pytest.mark.asyncio
async def test_graph_incremental_disposition_step(tmp_path, monkeypatch):
    from app.services.generation.graph import GraphRunner

    root = _write_memory(tmp_path, monkeypatch, generation_id="gen-inc-disp")
    state = _state(generation_id="gen-inc-disp", requirement="分页改为服务端分页")
    state["incremental_mode"] = True
    state["incremental_diff"] = {"added": [], "removed": [], "modified": [], "unchanged": [], "removed_ids": []}
    state["change_manifest"] = {
        "change_id": "chg-2026-08-05-001",
        "type": "behavior_change",
        "affected_modules": ["DataTable"],
        "affected_requirement_points": ["R-01"],
        "behavior_changes": [{"point": "R-01", "from": "客户端分页", "to": "服务端分页"}],
        "changed_requirements": ["R-01"],
        "changes": [],
    }
    state["change_id"] = "chg-2026-08-05-001"
    state["incremental_context"] = {
        "requirements": PRD, "requirements_size": len(PRD),
        "spec": None, "generated_files": {}, "e2e_manifest": {}, "features": [],
        "e2e_cases": inc.load_existing_cases(root),
    }
    runner = GraphRunner()
    events = [ev async for ev in runner.run(state, "gen-inc-disp")]
    cards = [e for e in events if e["event_type"] == "manager_message"]
    assert any("历史用例处置清单" in (e["data"].get("content") or "") for e in cards)
    assert "human_confirm_required" in [e["event_type"] for e in events]
    assert state["incremental_dispositions"][0]["disposition"] == "update"  # R-01 行为变更


@pytest.mark.asyncio
async def test_graph_incremental_pipeline_delta_prompt(tmp_path, monkeypatch):
    """全部确认后 → 增量流水线: phase-1 PRD prompt 携带已有需求 + manifest
    (delta 框定), 且输出完整 PRD (下游完整文档不变式)."""
    from app.services.generation.graph import GraphRunner

    root = _write_memory(tmp_path, monkeypatch, generation_id="gen-inc-pipe")
    state = _state(generation_id="gen-inc-pipe", requirement="分页改为服务端分页")
    state["incremental_mode"] = True
    state["incremental_diff"] = {"added": [], "removed": [], "modified": [], "unchanged": [], "removed_ids": []}
    state["change_manifest"] = {
        "change_id": "chg-2026-08-05-001",
        "type": "behavior_change",
        "affected_modules": ["DataTable"],
        "affected_requirement_points": ["R-01"],
        "behavior_changes": [{"point": "R-01", "from": "客户端分页", "to": "服务端分页"}],
        "changed_requirements": ["R-01"],
        "changes": [],
    }
    state["change_id"] = "chg-2026-08-05-001"
    state["test_dispositions"] = []
    state["incremental_context"] = {
        "requirements": PRD, "requirements_size": len(PRD),
        "spec": None, "generated_files": {}, "e2e_manifest": {}, "features": [],
        "e2e_cases": [],
    }
    captured: dict = {}

    async def fake_llm(system_prompt, user_content, **kwargs):
        captured["user_prompt"] = user_content
        return PRD

    runner = GraphRunner()
    with patch("app.services.generation.nodes._llm_generate", new_callable=AsyncMock, side_effect=fake_llm):
        events = [ev async for ev in runner.run(state, "gen-inc-pipe")]

    assert "prd_generate_start" in [e["event_type"] for e in events]
    prompt = captured["user_prompt"]
    assert "增量开发上下文" in prompt          # delta 框定
    assert "变更 manifest" in prompt
    assert "客户端分页" in prompt or "服务端分页" in prompt
    assert "完整" in prompt                    # 完整文档不变式 (prompt 层面)
    assert "human_confirm_required" in [e["event_type"] for e in events]
    assert state["analysis_result"] == PRD     # 全量 PRD 产物


@pytest.mark.asyncio
async def test_graph_incremental_disposition_retire_from_removed_ids(tmp_path, monkeypatch):
    """diff.removed_ids → R-03 用例 retire (端到端经 graph 入口处置步)."""
    from app.services.generation.graph import GraphRunner

    root = _write_memory(tmp_path, monkeypatch, generation_id="gen-inc-ret")
    state = _state(generation_id="gen-inc-ret", requirement="分页改为服务端分页")
    state["incremental_mode"] = True
    state["incremental_diff"] = {
        "added": [], "removed": ["旧功能"],
        "removed_ids": ["R-03"],
        "modified": [], "unchanged": [], "note": "",
    }
    state["change_manifest"] = {
        "change_id": "chg-2026-08-05-002",
        "type": "behavior_change",
        "affected_modules": ["DataTable"],
        "affected_requirement_points": ["R-01"],
        "behavior_changes": [{"point": "R-01", "from": "客户端分页", "to": "服务端分页"}],
        "changed_requirements": ["R-01"],
        "changes": [],
    }
    state["change_id"] = "chg-2026-08-05-002"
    state["incremental_context"] = {
        "requirements": PRD, "requirements_size": len(PRD),
        "spec": None, "generated_files": {}, "e2e_manifest": {}, "features": [],
        "e2e_cases": inc.load_existing_cases(root),
    }
    runner = GraphRunner()
    events = [ev async for ev in runner.run(state, "gen-inc-ret")]
    disp = {d["case_id"]: d for d in (state.get("incremental_dispositions") or [])}
    assert disp["tc-r01-1"]["disposition"] == "update"
    assert disp["tc-r03-1"]["disposition"] == "retire"   # removed_ids → retire
    assert any("历史用例处置清单" in (e["data"].get("content") or "")
               for e in events if e["event_type"] == "manager_message")


# ── 增量实现: planner delta 提示词 + 已有文件装载 ──


@pytest.mark.asyncio
async def test_incremental_planner_delta_prompt(tmp_path, monkeypatch):
    from app.services.generation import nodes

    root = _write_memory(tmp_path, monkeypatch, generation_id="gen-inc-plan")
    state = _state(generation_id="gen-inc-plan", requirement="分页改为服务端分页")
    state["incremental_mode"] = True
    state["change_manifest"] = {
        "type": "behavior_change",
        "affected_modules": ["DataTable"],
        "affected_requirement_points": ["R-01"],
        "behavior_changes": [{"point": "R-01", "from": "客户端分页", "to": "服务端分页"}],
    }
    state["incremental_context"] = {
        "generated_files": {"src/App.vue": "<template><div/></template>", "src/Table.vue": "x"},
    }
    state["architecture_spec"] = None
    state["design_doc"] = "# 设计方案\nDataTable.vue 改造"
    state["generated_files"] = {"src/App.vue": "<template><div/></template>", "src/Table.vue": "x"}
    captured: dict = {}
    dag_json = json.dumps({
        "reasoning": "delta",
        "tasks": [{"id": "task-0", "type": "business", "description": "改造分页",
                   "deps": [], "files": ["src/DataTable.vue"], "contract": {}}],
    })

    async def fake_llm(system_prompt, user_content, **kwargs):
        captured["user_prompt"] = user_content
        return dag_json

    queue = asyncio.Queue()
    with patch("app.services.generation.nodes._llm_generate", new_callable=AsyncMock, side_effect=fake_llm):
        result = await nodes.planner_node(state, queue)
    prompt = captured["user_prompt"]
    assert "增量开发上下文" in prompt
    assert "src/App.vue" in prompt            # 已有文件清单进上下文
    assert "只输出受影响模块的 delta 任务" in prompt
    tasks = result["planner_dag"]["tasks"]
    assert tasks[0]["files"] == ["src/DataTable.vue"]   # 只动受影响模块
    # 增量模式不清空已有文件 (全量模式才清空)
    assert result["generated_files"] == {"src/App.vue": "<template><div/></template>", "src/Table.vue": "x"}


@pytest.mark.asyncio
async def test_planner_full_mode_still_wipes_files(tmp_path, monkeypatch):
    from app.services.generation import nodes

    state = _state(generation_id="gen-full-plan")
    state["incremental_mode"] = False
    state["architecture_spec"] = None
    state["design_doc"] = "# 设计方案"
    state["generated_files"] = {"src/App.vue": "old"}

    async def fake_llm(system_prompt, user_content, **kwargs):
        return json.dumps({"reasoning": "x", "tasks": [
            {"id": "task-0", "type": "business", "description": "t", "deps": [], "files": ["src/App.vue"], "contract": {}},
        ]})

    queue = asyncio.Queue()
    with patch("app.services.generation.nodes._llm_generate", new_callable=AsyncMock, side_effect=fake_llm):
        result = await nodes.planner_node(state, queue)
    assert result["generated_files"] == {}


# ── 增量设计: 合并完整 Spec prompt ──


@pytest.mark.asyncio
async def test_generate_architecture_spec_merged_existing_spec():
    from app.services.generation.nodes import generate_architecture_spec

    existing = {"pages": [{"id": "p-01", "name": "用户列表页"}], "tech_stack": {"framework": "vue3"}}
    captured: dict = {}

    async def fake_llm(system_prompt, user_prompt):
        captured["user_prompt"] = user_prompt
        return json.dumps({
            "spec_version": 1,
            "tech_stack": {"framework": "vue3", "component_lib": "element-plus", "build": "webpack", "style": "scss"},
            "directory_tree": {"src/": ["main.ts", "App.vue"]},
            "data_model": [{"name": "User", "fields": [{"name": "id", "type": "string"}]}],
            "api_contracts": [{"name": "user/list", "method": "GET", "request": {}, "response": {}}],
            "routing": [{"path": "/", "page": "Home", "auth": False}],
            "state_management": {"store": "pinia", "stores": ["user"]},
            "component_tree": [{"name": "Header", "uses": [], "props": []}],
            "pages": [{"id": "p-01", "name": "用户列表页"}],
            "decisions": [{"topic": "选型", "choice": "element-plus", "reason": "用户选择"}],
        })

    spec, errors = await generate_architecture_spec(PRD, _state(), llm_fn=fake_llm, existing_spec=existing)
    assert errors == []
    assert spec["pages"][0]["name"] == "用户列表页"
    assert "已有架构 Spec" in captured["user_prompt"]
    assert "合并后的完整 Spec" in captured["user_prompt"]
    assert "用户列表页" in captured["user_prompt"]


# ── 回归模式 e2e designer: 保留历史用例 + 新增变更用例 ──


@pytest.mark.asyncio
async def test_e2e_designer_regression_mode_preserves_cases(tmp_path, monkeypatch):
    from app.services.generation import nodes

    root = _write_memory(tmp_path, monkeypatch, generation_id="gen-inc-e2e")
    state = _state(generation_id="gen-inc-e2e", requirement="分页改为服务端分页")
    state["analysis_result"] = PRD
    state["architecture_spec"] = None
    state["incremental_mode"] = True
    state["test_dispositions"] = [
        {"case_id": "tc-r01-1", "disposition": "keep", "reason": "未受影响"},
        {"case_id": "tc-r03-1", "disposition": "update", "reason": "行为变更"},
    ]
    # e2e_node 增量分支: 保留 keep 用例, update/retire 排除
    with patch(
        "app.services.generation.e2e_designer.run_e2e_designer",
        new_callable=AsyncMock,
    ) as mock_designer:
        mock_designer.return_value = {
            "requirement_points": [], "cases": [], "coverage": {},
            "dropped": [], "errors": [], "md": "", "written": {},
            "card_payload": {}, "card_content": "",
        }
        result = await nodes.e2e_node(state)
    preserved = mock_designer.call_args.kwargs.get("existing_cases") or []
    assert [c["id"] for c in preserved] == ["tc-r01-1"]  # update 用例不保留 (重设计)


@pytest.mark.asyncio
async def test_run_e2e_designer_existing_cases_preserved_and_id_reuse_guard():
    from app.services.generation.e2e_designer import run_e2e_designer

    preserved = [{
        "id": "tc-r01-1",
        "requirement_id": "R-01",
        "scenario": "分页切换",
        "steps": [{"action": "assert", "target": {"by": "text", "value": "第 2 页"}, "assertion": "contains"}],
    }]
    state = _state(requirements_state_json=json.dumps({
        "features": [{"id": "R-01", "name": "分页功能"}, {"id": "R-02", "name": "订单管理"}],
    }))

    async def fake_llm(system_prompt, user_prompt):
        # 模型违规复用既有 id tc-r01-1 → 应被保留集守卫拦截
        return json.dumps({"cases": [
            {"id": "tc-r01-1", "requirement_id": "R-01", "scenario": "覆盖尝试", "steps": []},
            {"id": "tc-r02-1", "requirement_id": "R-02", "scenario": "订单列表",
             "steps": [{"action": "assert", "target": {"by": "text", "value": "订单"}, "assertion": "contains"}]},
        ], "coverage_matrix": {}})

    report = await run_e2e_designer(state, llm_fn=fake_llm, project_root=None, existing_cases=preserved)
    by_id = {c["id"]: c for c in report["cases"]}
    assert by_id["tc-r01-1"]["scenario"] == "分页切换"      # 保留用例未被覆盖
    assert by_id["tc-r02-1"]["scenario"] == "订单列表"      # 新用例加入


# ── load_incremental_context (8.1) ──


def test_load_incremental_context(tmp_path, monkeypatch):
    root = _write_memory(tmp_path, monkeypatch, generation_id="gen-inc-ctx")
    ctx = inc.load_incremental_context(root)
    assert ctx["requirements"] == PRD
    assert ctx["requirements_size"] == len(PRD)
    # features 携带 id (state.json 有 id 时) — removed_ids 判定键
    assert ctx["features"] == [{"id": "F-01", "name": "用户管理"}]
    assert "src/App.vue" in ctx["generated_files"]
    assert ctx["e2e_cases"][0]["id"] == "tc-r01-1"
    assert ctx["e2e_manifest"]["tc-r01-1"] == STATUS_ACTIVE
    assert ctx["spec"] is None  # 未写 architecture.json


# ── code review fixes (C1/I1/I2/I3/I4/M1/M2) ──


@pytest.mark.asyncio
async def test_graph_incremental_empty_dispositions_advances(tmp_path, monkeypatch):
    """C1: 无历史 E2E 用例 → 处置清单为空 [] → 确认后必须越过 step C 进入
    增量流水线 (不得死循环重发卡片)."""
    from app.services.generation import memory
    from app.services.generation.graph import GraphRunner

    monkeypatch.setenv("AI_GEN_DATA_DIR", str(tmp_path))
    state = _state(generation_id="gen-inc-empty", requirement="分页改为服务端分页")
    root = memory.project_root_for(state)
    memory.write_requirements(root, PRD)
    memory.write_state(root, _state(requirements_state_json=json.dumps(
        {"features": [{"id": "F-01", "name": "用户管理"}]}
    )))
    memory.update_index(root, stage="code")
    state["incremental_mode"] = True
    state["incremental_diff"] = {"added": [], "removed": [], "modified": [], "unchanged": [], "removed_ids": []}
    state["change_manifest"] = {
        "change_id": "chg-2026-08-05-003",
        "type": "behavior_change",
        "affected_modules": ["DataTable"],
        "affected_requirement_points": ["R-01"],
        "behavior_changes": [{"point": "R-01", "from": "客户端分页", "to": "服务端分页"}],
        "changed_requirements": ["R-01"],
        "changes": [],
    }
    state["change_id"] = "chg-2026-08-05-003"
    state["incremental_context"] = {
        "requirements": PRD, "requirements_size": len(PRD),
        "spec": None, "generated_files": {}, "e2e_manifest": {}, "features": [],
        "e2e_cases": [],  # 无历史用例
    }
    captured: dict = {}

    async def fake_llm(system_prompt, user_content, **kwargs):
        captured["prd"] = user_content
        return PRD

    runner = GraphRunner()
    with patch("app.services.generation.nodes._llm_generate", new_callable=AsyncMock, side_effect=fake_llm):
        ev1 = [e async for e in runner.run(state, "gen-inc-empty")]
        # 空清单也是有效结果: 发卡片并停等, 不重算
        assert state.get("incremental_dispositions") == []
        cards1 = [e for e in ev1 if e["event_type"] == "manager_message"]
        assert any("历史用例处置清单" in (e["data"].get("content") or "") for e in cards1)
        assert "prd_generate_start" not in [e["event_type"] for e in ev1]

        ev2 = [e async for e in runner.resume("gen-inc-empty")]
    assert "prd_generate_start" in [e["event_type"] for e in ev2]   # 越过 step C → 增量 PRD
    assert state.get("test_dispositions") == []
    assert "增量开发上下文" in captured.get("prd", "")


@pytest.mark.asyncio
async def test_graph_incremental_confirm_flow_via_resume(tmp_path, monkeypatch):
    """M6: 驱动真实 runner.resume() 走完整确认流 diff → manifest → 处置 → 流水线."""
    from app.services.generation.graph import GraphRunner

    root = _write_memory(tmp_path, monkeypatch, generation_id="gen-inc-res")
    state = _state(generation_id="gen-inc-res", requirement="分页改为服务端分页")
    state["incremental_mode"] = True
    captured: dict = {}

    async def fake_llm(system_prompt, user_content, **kwargs):
        if "变更 manifest" in system_prompt:
            return MANIFEST_JSON
        captured["prd"] = user_content
        return PRD

    runner = GraphRunner()
    with patch("app.services.generation.nodes._llm_generate", new_callable=AsyncMock, side_effect=fake_llm):
        ev1 = [e async for e in runner.run(state, "gen-inc-res")]
        assert any("增量变更清单" in (e["data"].get("content") or "")
                   for e in ev1 if e["event_type"] == "manager_message")
        assert state.get("incremental_diff") is not None
        assert "prd_generate_start" not in [e["event_type"] for e in ev1]

        ev2 = [e async for e in runner.resume("gen-inc-res")]
        assert any("变更 manifest" in (e["data"].get("content") or "")
                   for e in ev2 if e["event_type"] == "manager_message")
        assert state.get("change_manifest") is not None
        assert state.get("change_id")

        ev3 = [e async for e in runner.resume("gen-inc-res")]
        assert any("历史用例处置清单" in (e["data"].get("content") or "")
                   for e in ev3 if e["event_type"] == "manager_message")
        assert state.get("incremental_dispositions") is not None

        ev4 = [e async for e in runner.resume("gen-inc-res")]
    assert "prd_generate_start" in [e["event_type"] for e in ev4]
    assert "增量开发上下文" in captured.get("prd", "")
    assert state.get("test_dispositions") is not None


@pytest.mark.asyncio
async def test_regen_incremental_step_clears_pending(tmp_path, monkeypatch):
    """I1: 「重新生成」清除当前待确认级产物, resume 后从该级重算."""
    from app.services.generation.graph import GraphRunner

    root = _write_memory(tmp_path, monkeypatch, generation_id="gen-inc-regen")
    state = _state(generation_id="gen-inc-regen", requirement="分页改为服务端分页")
    state["incremental_mode"] = True
    state["incremental_diff"] = {"added": [], "removed": [], "modified": [], "unchanged": [], "removed_ids": []}
    state["incremental_context"] = {
        "requirements": PRD, "requirements_size": len(PRD),
        "spec": None, "generated_files": {}, "e2e_manifest": {}, "features": [],
        "e2e_cases": inc.load_existing_cases(root),
    }
    runner = GraphRunner()
    runner._state = state

    # 处置级: 清除 draft → 重算处置
    state["incremental_dispositions"] = [{"case_id": "tc-r01-1", "disposition": "keep"}]
    runner.regen_incremental_step()
    assert state.get("incremental_dispositions") is None

    # manifest 级: 清除 manifest → 重新生成
    state["change_manifest"] = {"change_id": "x", "type": "new_feature"}
    state["change_id"] = "x"
    runner.regen_incremental_step()
    assert state.get("change_manifest") is None
    assert state.get("change_id") is None

    # diff 级: 清除 diff → 重新分类
    runner.regen_incremental_step()
    assert state.get("incremental_diff") is None

    # 非增量模式无操作
    state["incremental_mode"] = False
    state["incremental_diff"] = {"added": ["x"]}
    runner.regen_incremental_step()
    assert state.get("incremental_diff") == {"added": ["x"]}


def test_filter_delta_tasks_strips_untouched_existing_files():
    """I3: 存量且不受影响模块的文件从任务剔除; 跨任务重复文件去重."""
    existing = {"src/App.vue": "x", "src/DataTable.vue": "y"}
    tasks = [
        {"id": "task-0", "files": ["src/DataTable.vue"], "deps": []},                          # 存量但受影响 → 保留
        {"id": "task-1", "files": ["src/App.vue"], "deps": ["task-0"]},                        # 存量未受影响 → 剔除
        {"id": "task-2", "files": ["src/NewTable.vue", "src/DataTable.vue"], "deps": []},      # 新增 + 重复 → 去重
    ]
    filtered = inc.filter_delta_tasks(tasks, existing, ["DataTable"])
    files = [f for t in filtered for f in t["files"]]
    assert "src/App.vue" not in files
    assert files.count("src/DataTable.vue") == 1
    assert "src/NewTable.vue" in files     # 新增文件不在存量清单 → 保留
    assert "task-1" not in {t["id"] for t in filtered}   # 空文件任务剔除


def test_filter_delta_tasks_fail_open_when_emptied():
    """I3: 过度剔除 (fallback DAG 全量存量) → 回退为仅去重, 不空转."""
    existing = {"src/App.vue": "x", "src/Header.vue": "y"}
    tasks = [{"id": "task-0", "files": ["src/App.vue", "src/Header.vue"], "deps": []}]
    filtered = inc.filter_delta_tasks(tasks, existing, ["DataTable"])
    assert {f for t in filtered for f in t["files"]} == {"src/App.vue", "src/Header.vue"}


@pytest.mark.asyncio
async def test_generate_manifest_strips_behavior_changes_for_non_behavior_types(tmp_path, monkeypatch):
    """I4: new_feature/refactor/visual 的 behavior_changes 确定性剔除 —
    不得让诊断器把真回归当预期失效。"""
    monkeypatch.setenv("AI_GEN_DATA_DIR", str(tmp_path))

    async def fake_llm(system_prompt, user_prompt):
        return ('{"type": "refactor", "affected_modules": ["X"], '
                '"affected_requirement_points": ["R-01"], '
                '"behavior_changes": [{"point": "R-01", "from": "a", "to": "b"}]}')

    manifest = await inc.generate_manifest(_state(), diff=None, llm_fn=fake_llm)
    assert manifest["type"] == "refactor"
    assert manifest["behavior_changes"] == []
    assert manifest["changed_requirements"] == []   # 重构 → 不遮蔽真回归
    assert manifest["changes"] == []


@pytest.mark.asyncio
async def test_incremental_verifier_hooks_scoped_to_touched_files(tmp_path, monkeypatch):
    """I2: 增量模式埋点钩子只扫本次变更触碰的文件 — 存量缺钩子不误判失败
    (否则触发整仓重生成, 违反只动受影响模块)。"""
    from types import SimpleNamespace

    from app.services.generation.verifier import run_verifier

    class _FakeRegistry:
        async def invoke(self, name, args):
            return SimpleNamespace(ok=True, data={})

        def get_frontend_compile_errors(self):
            return []

        def get_runtime_errors(self):
            return []

    legacy = "<template><button>旧按钮</button></template>"          # 存量: 无 testid
    touched = "<template><button data-testid=\"save\">存</button></template>"  # 本次修改: 有钩子
    brand_new = "<template><button>新提交</button></template>"       # 本次新增: 无钩子 → 违规

    state = _state(
        generated_files={"src/App.vue": legacy, "src/Touched.vue": touched, "src/NewForm.vue": brand_new},
        code_result="{\"x\": \"<template><div/></template>\"}",
        incremental_mode=True,
        incremental_context={"generated_files": {
            "src/App.vue": legacy,
            "src/Touched.vue": "<template><button>旧存</button></template>",  # 内容变化 → 触碰
        }},
    )
    result = await run_verifier(state, _FakeRegistry(), tier="S")
    violated = {v["file"] for v in result["evidence"]["hook_violations"]}
    assert "src/App.vue" not in violated            # 存量 (未触碰) 不扫描
    assert "src/NewForm.vue" in violated            # 新增文件扫描
    assert "src/Touched.vue" not in violated        # 触碰但已有钩子

    # 非增量模式: 全量扫描 → 存量缺钩子也报违规
    state2 = dict(state)
    state2.pop("incremental_mode")
    state2.pop("incremental_context")
    result2 = await run_verifier(state2, _FakeRegistry(), tier="S")
    violated2 = {v["file"] for v in result2["evidence"]["hook_violations"]}
    assert "src/App.vue" in violated2


def test_regression_accounting_maps_diag_expected_broken_to_expected():
    """M1: 诊断 expected_broken 但 manifest 状态翻转失败 → counts 记 expected
    而非泄漏诊断桶名。"""
    state = _state(e2e_test_cases=[{"id": "tc-x", "requirement_id": "R-01", "steps": []}])
    results = [{"case_id": "tc-x", "passed": False, "status": "failed"}]
    diagnosis = {"diagnoses": [{"case_id": "tc-x", "classification": EXPECTED_BROKEN}]}
    accounting = inc.build_regression_accounting(state, results, diagnosis, [], "/nonexistent")
    assert accounting["cases"][0]["result"] == "expected"
    assert "expected" in accounting["counts"]


@pytest.mark.asyncio
async def test_e2e_designer_resets_status_for_reused_ids(tmp_path, monkeypatch):
    """M2: 增量回归模式下, 新用例复用归档 id → 状态重置为 active (否则永不执行)."""
    from app.services.generation.e2e_designer import run_e2e_designer

    root = _write_memory(tmp_path, monkeypatch, generation_id="gen-inc-m2")
    # 先把 tc-r02-1 归档 (模拟历史归档 id 被模型复用)
    inc.apply_dispositions(root, [{"case_id": "tc-r03-1", "disposition": "retire"}])
    preserved = [{
        "id": "tc-r01-1",
        "requirement_id": "R-01",
        "scenario": "分页切换",
        "steps": [{"action": "assert", "target": {"by": "text", "value": "第 2 页"}, "assertion": "contains"}],
    }]
    state = _state(requirements_state_json=json.dumps({
        "features": [{"id": "R-01", "name": "分页功能"}, {"id": "R-02", "name": "订单管理"}],
    }))

    async def fake_llm(system_prompt, user_prompt):
        # 模型违规复用归档 id tc-r03-1
        return json.dumps({"cases": [
            {"id": "tc-r03-1", "requirement_id": "R-02", "scenario": "订单列表",
             "steps": [{"action": "assert", "target": {"by": "text", "value": "订单"}, "assertion": "contains"}]},
        ], "coverage_matrix": {}})

    report = await run_e2e_designer(state, llm_fn=fake_llm, project_root=root, existing_cases=preserved)
    statuses = inc.load_e2e_manifest(root)
    assert statuses["tc-r03-1"] == STATUS_ACTIVE        # 复用归档 id → 重置 active
    assert statuses["tc-r01-1"] == STATUS_ACTIVE        # 保留用例状态不变
