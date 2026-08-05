"""Tests for the manager-worker orchestration skeleton (manager_gate)."""

import json

import pytest
from langgraph.graph import END

from app.services.generation.graph import build_graph, decide_after_gate
from app.services.generation.manager import (
    evaluate_stage_l2,
    infer_last_worker,
    manager_gate,
    record_verdict,
    run_l1_checks,
)

PRD_OK = (
    "# 需求规格文档\n\n"
    "## 1. 功能概述\n...\n\n"
    "## 2. 功能模块\n- 用户管理\n\n"
    "## 3. 页面结构\n- 用户列表页\n\n"
    "## 4. 数据模型\n\n## 5. 交互行为\n"
)
DESIGN_OK = "# 设计方案\n组件树结构\n数据流设计\n样式方案\n文件拆分方案\n关键实现要点"
# Valid architecture spec (D5, 4.2) — required by the design L1 gate (4.3).
SPEC_OK = {
    "spec_version": 1,
    "tech_stack": {"framework": "vue3", "component_lib": "element-plus", "build": "webpack", "style": "scss"},
    "directory_tree": {"src/": ["main.ts", "App.vue", "router/", "components/"]},
    "data_model": [{"name": "User", "fields": [{"name": "id", "type": "string"}]}],
    "api_contracts": [{"name": "user/list", "method": "GET", "request": {}, "response": {}}],
    "routing": [{"path": "/", "page": "Home", "auth": False}],
    "state_management": {"store": "pinia", "stores": ["user"]},
    "component_tree": [{"name": "Header", "uses": ["NavMenu"], "props": []}],
    "pages": [{"id": "p-01", "name": "登录页", "interactions": [], "data": []}],
    "decisions": [{"topic": "技术选型", "choice": "element-plus", "reason": "用户选择"}],
}


def _make_state(**overrides) -> dict:
    state = {
        "requirement": "生成一个用户管理页面",
        "component_lib": "element-plus",
        "messages": [{"role": "user", "content": "生成一个用户管理页面"}],
        "requirements_state_json": None,
        "analysis_result": None,
        "design_result": None,
        "code_result": None,
        "e2e_results": None,
        "e2e_test_cases": None,
        "e2e_passed": False,
        "failure_details": None,
        "qa_rounds": 0,
        "rollback_records": [],
        "rollback_count": {},
        "max_rollback_per_node": 3,
        "max_rollback_total": 10,
        "needs_manual_review": False,
        "stage_phase": "complete",
        "design_doc": None,
        "architecture_spec": None,
        "generated_files": {},
        "compile_errors": None,
        "e2e_test_cases_md": None,
        "e2e_user_confirmed": False,
        "dispatch_contract": None,
        "manager_verdicts": [],
    }
    state.update(overrides)
    return state


def _code_state(files: dict[str, str] | None = None, compile_errors=None, **overrides) -> dict:
    files = files if files is not None else {
        "App.vue": "<template><div>hi</div></template>",
    }
    return _make_state(
        code_result=json.dumps(files, ensure_ascii=False),
        generated_files=files,
        compile_errors=compile_errors,
        **overrides,
    )


# ---------------------------------------------------------------------------
# Graph topology
# ---------------------------------------------------------------------------


def test_graph_topology_review_removed():
    """The graph is supervisor-shaped: gate + code/e2e workers, no review."""
    graph = build_graph().get_graph()
    nodes = set(graph.nodes.keys())
    assert {"manager_gate", "code", "e2e"} <= nodes
    assert "review" not in nodes
    assert "analysis" not in nodes
    assert "design" not in nodes

    edges = {(e.source, e.target) for e in graph.edges}
    # every worker returns to the gate
    assert ("code", "manager_gate") in edges
    assert ("e2e", "manager_gate") in edges


def test_graph_compile_interrupts_before_workers():
    app = build_graph()
    assert set(app.interrupt_before_nodes) == {"code", "e2e"}


def test_decide_after_gate_routing():
    assert decide_after_gate(_make_state(manager_next="e2e")) == "e2e"
    assert decide_after_gate(_make_state(manager_next="code")) == "code"
    assert decide_after_gate(_make_state(manager_next="end")) == END
    # missing decision defaults to dispatching the e2e worker
    assert decide_after_gate(_make_state()) == "e2e"


@pytest.mark.asyncio
async def test_graph_astream_gate_pauses_before_e2e():
    """Entry with code done: gate passes code and pauses before the e2e worker."""
    app = build_graph()
    config = {"configurable": {"thread_id": "t-e2e"}}
    events = []
    async for event in app.astream(_code_state(), config):
        events.append(event)

    gate_output = next(e["manager_gate"] for e in events if "manager_gate" in e)
    assert gate_output["manager_next"] == "e2e"
    assert gate_output["manager_verdicts"][-1]["node"] == "code"
    assert gate_output["manager_verdicts"][-1]["decision"] == "pass"

    snapshot = app.get_state(config)
    assert snapshot.next == ("e2e",)


@pytest.mark.asyncio
async def test_graph_astream_gate_redo_pauses_before_code():
    """Entry with no code output: L1 fails and the gate re-dispatches code."""
    app = build_graph()
    config = {"configurable": {"thread_id": "t-redo"}}
    events = []
    async for event in app.astream(_make_state(), config):
        events.append(event)

    gate_output = next(e["manager_gate"] for e in events if "manager_gate" in e)
    assert gate_output["manager_next"] == "code"
    assert gate_output["manager_verdicts"][-1]["decision"] == "redo"

    snapshot = app.get_state(config)
    assert snapshot.next == ("code",)


@pytest.mark.asyncio
async def test_runner_phase4_gate_flow():
    """GraphRunner.run() phase 4: gate dedupes the already-gated code output,
    announces the paused worker, and emits no bogus stage events.

    Runs the real graph with all phases pre-filled (no LLM involved — the gate
    is deterministic and the graph pauses before the e2e worker). The design
    stage now carries the Spec (4.2) and runs the L2 gate (4.4) — a fake
    llm_fn passes L2.
    """
    from app.services.generation.graph import GraphRunner

    async def _l2_pass(_system: str, _user: str) -> str:
        return '{"passed": true, "missing": []}'

    runner = GraphRunner(llm_fn=_l2_pass)
    state = _make_state(
        analysis_result=PRD_OK,
        design_result=DESIGN_OK,
        architecture_spec=SPEC_OK,
        code_result=json.dumps({"App.vue": "<template>x</template>"}),
        generated_files={"App.vue": "<template>x</template>"},
    )
    # simulate the manual phases' gate verdicts (as GraphRunner.run records them)
    await runner._gate_manual_stage(state, "analysis")
    await runner._gate_manual_stage(state, "design")
    await runner._gate_manual_stage(state, "code")

    events = [ev async for ev in runner.run(state, "gen-phase4")]

    types = [e["event_type"] for e in events]
    stages = [e["stage"] for e in events]
    # the phase-4 gate re-judges the identical code output — verdict deduped,
    # so no duplicate record/event
    assert "manager_verdict" not in types
    assert "__interrupt__" not in stages
    assert "manager_gate" not in stages

    confirm = next(e for e in events if e["event_type"] == "human_confirm_required")
    assert confirm["stage"] == "e2e"
    assert "把关通过" in confirm["data"]["message"]

    # checkpoint keeps exactly the 3 manual verdicts — no 4th duplicate
    snapshot = runner.app.get_state({"configurable": {"thread_id": "gen-phase4"}})
    assert [v["node"] for v in snapshot.values["manager_verdicts"]] == ["analysis", "design", "code"]


@pytest.mark.asyncio
async def test_gate_manual_stage_emits_verdict():
    """Manual phases (analysis/design/code) run the gate and emit verdict events.

    Since task group 2, the verdict is followed by the Manager speech cards
    (task 2.4): summary_card + verdict_card on pass, diagnosis_card on fail.
    """
    from app.services.generation.graph import GraphRunner

    runner = GraphRunner()
    state = _make_state(analysis_result=PRD_OK)

    events = await runner._gate_manual_stage(state, "analysis")
    assert len(events) == 3
    assert events[0]["event_type"] == "manager_verdict"
    assert events[0]["stage"] == "analysis"
    assert events[0]["data"]["decision"] == "pass"
    assert state["manager_verdicts"][-1]["node"] == "analysis"
    assert runner._verdicts_emitted == 1
    # pass → summary_card + verdict_card
    assert [e["event_type"] for e in events[1:]] == ["manager_message", "manager_message"]
    assert [e["data"]["card"] for e in events[1:]] == ["summary_card", "verdict_card"]
    assert events[1]["data"]["content"] == PRD_OK[:200]

    # L1 failure → redo verdict + diagnosis_card
    events2 = await runner._gate_manual_stage(_make_state(analysis_result=""), "analysis")
    assert events2[0]["data"]["decision"] == "redo"
    assert events2[1]["event_type"] == "manager_message"
    assert events2[1]["data"]["card"] == "diagnosis_card"
    assert events2[1]["data"]["content"]


def test_manager_verdict_events_emit_cards():
    """Phase-4 gate verdicts stream their Manager speech cards too (task 2.4)."""
    from app.services.generation.graph import GraphRunner

    runner = GraphRunner()
    state = _make_state(
        analysis_result=PRD_OK,
        manager_verdicts=[
            {"node": "analysis", "decision": "pass", "reason": "", "signature": "s1", "at": "t"},
        ],
    )
    events = runner._manager_verdict_events(state)
    assert len(events) == 3
    assert events[0]["event_type"] == "manager_verdict"
    assert events[0]["data"]["decision"] == "pass"
    assert [e["data"]["card"] for e in events[1:]] == ["summary_card", "verdict_card"]

    # dedupe: same verdict slice already emitted → no events on next call
    assert runner._manager_verdict_events(state) == []

    # fail verdict → diagnosis_card with L1 evidence
    runner2 = GraphRunner()
    state2 = _make_state(
        code_result=None,
        manager_verdicts=[
            {"node": "code", "decision": "redo", "reason": "Generated code is empty", "signature": "s2", "at": "t"},
        ],
    )
    events2 = runner2._manager_verdict_events(state2)
    assert events2[0]["data"]["decision"] == "redo"
    assert events2[1]["data"]["card"] == "diagnosis_card"
    assert events2[1]["data"]["content"]


@pytest.mark.asyncio
async def test_runner_announces_paused_worker():
    """Pause announcement fires only without a pending confirm; wording follows the last verdict."""
    from app.services.generation.graph import GraphRunner

    runner = GraphRunner()
    config = {"configurable": {"thread_id": "t-announce"}}

    class FakeSnap:
        def __init__(self, next_node, verdicts):
            self.next = (next_node,)
            self.values = {"manager_verdicts": verdicts}

    # pass verdict → confirm wording
    runner.app.get_state = lambda cfg: FakeSnap("e2e", [{"node": "code", "decision": "pass", "reason": ""}])
    events = [ev async for ev in runner._announce_paused_worker(config, confirm_emitted=False)]
    assert [e["event_type"] for e in events] == ["stage_start", "human_confirm_required"]
    assert events[0]["stage"] == "e2e"
    assert "把关通过" in events[1]["data"]["message"]

    # redo verdict → rework wording (regression for the hardcoded-message bug)
    runner.app.get_state = lambda cfg: FakeSnap("code", [{"node": "code", "decision": "redo", "reason": "编译未通过"}])
    events2 = [ev async for ev in runner._announce_paused_worker(config, confirm_emitted=False)]
    assert events2[0]["stage"] == "code"
    assert "未通过" in events2[1]["data"]["message"]

    # a pending confirm in the stream suppresses the announcement
    events3 = [ev async for ev in runner._announce_paused_worker(config, confirm_emitted=True)]
    assert events3 == []


@pytest.mark.asyncio
async def test_runner_phase4_announce_message_matches_verdict():
    """A redo verdict (L1 fail) yields the rework confirmation wording in the real flow."""
    from app.services.generation.graph import GraphRunner

    runner = GraphRunner()
    state = _make_state(
        analysis_result=PRD_OK,
        design_result=DESIGN_OK,
        code_result=json.dumps({"App.ts": "export const a = 1"}),  # no <template> → L1 fail
        generated_files={"App.ts": "export const a = 1"},
    )

    events = [ev async for ev in runner.run(state, "gen-redo-msg")]

    confirms = [e for e in events if e["event_type"] == "human_confirm_required"]
    assert confirms and confirms[0]["stage"] == "code"
    assert "未通过" in confirms[0]["data"]["message"]


@pytest.mark.asyncio
async def test_runner_resume_gate_worker_gate_cycle():
    """resume(): gate → e2e worker (Test Designer) → gate pauses at e2e.

    Group 6 routing: cases generated but NOT yet confirmed by the user → the
    gate routes back to the e2e worker's interrupt (pause), NOT to the code
    worker (the old rollback behavior pinned before the TODO fix).
    """
    from unittest.mock import AsyncMock, patch

    from app.services.generation.graph import GraphRunner

    DESIGNER_JSON = json.dumps({
        "cases": [
            {
                "id": "tc-r01-1", "requirement_id": "R-01", "scenario": "页面加载",
                "steps": [
                    {"action": "wait", "target": {"by": "css", "value": "#app"}},
                    {"action": "assert", "target": {"by": "text", "value": "用户管理"},
                     "assertion": "contains"},
                ],
                "requires_browser": False,
            },
        ],
        "coverage_matrix": {"R-01": ["tc-r01-1"]},
    }, ensure_ascii=False)

    runner = GraphRunner()
    state = _make_state(
        analysis_result=PRD_OK,
        design_result=DESIGN_OK,
        code_result=json.dumps({"App.vue": "<template>x</template>"}),
        generated_files={"App.vue": "<template>x</template>"},
    )
    config = {"configurable": {"thread_id": "gen-cycle"}}

    # phase-4 entry: gate passes code, pauses before the e2e worker
    events = [ev async for ev in runner.run(state, "gen-cycle")]
    confirms = [e for e in events if e["event_type"] == "human_confirm_required"]
    assert confirms and confirms[0]["stage"] == "e2e"

    # resume: e2e worker runs (Designer via mocked LLM) → gate pauses at e2e
    # (awaiting user confirmation of the generated cases)
    with patch("app.services.generation.nodes._llm_generate", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = DESIGNER_JSON
        events = [ev async for ev in runner.resume("gen-cycle")]

    types = [e["event_type"] for e in events]
    stages = [e["stage"] for e in events]
    assert "e2e" in stages                       # e2e worker ran
    assert "manager_verdict" in types            # gate verdict for e2e
    assert "manager_gate" not in stages
    # coverage matrix card + DSL cases are emitted for the frontend
    coverage = [e for e in events if e["event_type"] == "manager_message"
                and e["data"].get("card") == "coverage_matrix"]
    assert coverage and coverage[0]["data"]["data"]["matrix"]["R-01"]["case_ids"] == ["tc-r01-1"]
    gen_done = [e for e in events if e["event_type"] == "e2e_cases_gen_done"]
    assert gen_done and gen_done[0]["data"]["cases"][0]["id"] == "tc-r01-1"

    # group 6 routing: unconfirmed cases pause at the e2e worker interrupt —
    # no rollback to the code worker
    snapshot = runner.app.get_state(config)
    assert snapshot.next == ("e2e",)
    assert snapshot.values["manager_verdicts"][-1]["node"] == "e2e"
    assert snapshot.values["e2e_user_confirmed"] is False

    # I3: resume WITHOUT the explicit e2e_confirmed flag (e.g. chat-intent
    # proceed) must NOT auto-confirm the cases — no execute hand-off
    events_noconfirm = [ev async for ev in runner.resume("gen-cycle")]
    assert not [e for e in events_noconfirm if e["event_type"] == "e2e_execute_start"]
    assert runner.app.get_state(config).values["e2e_user_confirmed"] is False

    # phase-2 resume (user confirmed via the E2EStagePanel button, which sends
    # the explicit flag): resume() syncs the confirmation into the checkpoint →
    # pass-through → e2e_execute_start hands the DSL cases to the frontend
    # runner (no second confirm prompt, no Designer re-run)
    events2 = [ev async for ev in runner.resume("gen-cycle", e2e_confirmed=True)]

    exec_start = [e for e in events2 if e["event_type"] == "e2e_execute_start"]
    assert exec_start and exec_start[0]["data"]["test_cases"][0]["id"] == "tc-r01-1"
    assert not [e for e in events2 if e["event_type"] == "human_confirm_required"]
    assert runner.app.get_state(config).values["e2e_user_confirmed"] is True


@pytest.mark.asyncio
async def test_manager_gate_appends_verdict_and_records_history():
    state = _code_state()
    out = await manager_gate(state)
    assert len(out["manager_verdicts"]) == 1
    verdict = out["manager_verdicts"][-1]
    assert verdict["node"] == "code"
    assert verdict["decision"] == "pass"
    assert verdict["signature"]
    assert "at" in verdict

    # second pass appends to the history (memory skeleton)
    out2 = await manager_gate(_make_state(manager_next="e2e", e2e_results=[]))
    assert len(out2["manager_verdicts"]) == 1
    assert out2["manager_next"] == "code"  # e2e done without pass → rollback path


@pytest.mark.asyncio
async def test_manager_gate_dedupes_identical_output_and_reevaluates_changes():
    """Same output → verdict reused (no re-record); changed output → re-judged."""
    state = _code_state()
    record_verdict(state, "code", "pass", "")   # e.g. the manual-phase verdict
    out = await manager_gate(state)
    assert len(out["manager_verdicts"]) == 1            # deduped
    assert out["manager_next"] == "e2e"
    assert out["manager_verdicts"][-1]["signature"] == state["manager_verdicts"][0]["signature"]

    # output changed → re-evaluated and a new verdict recorded
    changed = _code_state({"App.vue": "<template>changed</template>"})
    changed["manager_verdicts"] = list(state["manager_verdicts"])
    out2 = await manager_gate(changed)
    assert len(out2["manager_verdicts"]) == 2
    assert out2["manager_verdicts"][-1]["decision"] == "pass"
    assert out2["manager_next"] == "e2e"


# ---------------------------------------------------------------------------
# L1 gating
# ---------------------------------------------------------------------------


def test_run_l1_checks_analysis():
    assert run_l1_checks(_make_state(analysis_result=PRD_OK), "analysis") == []
    assert run_l1_checks(_make_state(analysis_result=""), "analysis") != []
    assert run_l1_checks(_make_state(analysis_result="# 缺少功能模块章节"), "analysis") != []


def test_run_l1_checks_design():
    # L1 for design = MD sections + Spec field completeness (4.3): both are
    # required — a valid spec passes, a missing/partial one fails.
    assert run_l1_checks(
        _make_state(design_result=DESIGN_OK, architecture_spec=SPEC_OK), "design"
    ) == []
    assert run_l1_checks(_make_state(design_result=DESIGN_OK), "design") != []
    assert run_l1_checks(_make_state(design_result=""), "design") != []


def test_run_l1_checks_code():
    assert run_l1_checks(_code_state(), "code") == []
    # missing <template> in generated code
    bad = _code_state({"App.ts": "export const x = 1"})
    assert run_l1_checks(bad, "code") != []
    # compile errors fail L1
    failed = _code_state(compile_errors=[{"file": "App.vue", "line": 1, "message": "syntax"}])
    assert run_l1_checks(failed, "code") != []
    # empty code fails L1
    assert run_l1_checks(_make_state(code_result=None), "code") != []


def test_run_l1_checks_e2e():
    ok = _make_state(e2e_results=[{"case_id": "tc-1", "passed": True}])
    assert run_l1_checks(ok, "e2e") == []
    failed = _make_state(e2e_results=[{"case_id": "tc-1", "passed": False, "error": "boom"}])
    assert run_l1_checks(failed, "e2e") != []


@pytest.mark.asyncio
async def test_evaluate_stage_l2_decision_labels():
    decision, reason, evidence, missing = await evaluate_stage_l2(_code_state(), "code")
    assert (decision, reason, evidence, missing) == ("pass", "", [], [])
    decision, reason, _ev, _miss = await evaluate_stage_l2(_make_state(code_result=None), "code")
    assert decision == "redo"
    assert reason
    failed_e2e = _make_state(e2e_results=[{"case_id": "tc-1", "passed": False}])
    decision, *_ = await evaluate_stage_l2(failed_e2e, "e2e")
    assert decision == "rollback"
    decision, *_ = await evaluate_stage_l2(_make_state(e2e_results=[]), "e2e")
    assert decision == "pass"


def test_record_verdict_appends():
    state = _make_state()
    record_verdict(state, "analysis", "pass", "")
    record_verdict(state, "design", "pass", "")
    assert len(state["manager_verdicts"]) == 2
    assert state["manager_verdicts"][0]["node"] == "analysis"
    assert state["manager_verdicts"][1]["decision"] == "pass"


def test_infer_last_worker():
    assert infer_last_worker(_make_state()) == "code"
    assert infer_last_worker(_make_state(analysis_result=PRD_OK)) == "analysis"
    assert infer_last_worker(_make_state(analysis_result=PRD_OK, design_result=DESIGN_OK)) == "design"
    assert infer_last_worker(_code_state()) == "code"
    assert infer_last_worker(_code_state(e2e_results=[{"case_id": "tc-1", "passed": True}])) == "e2e"


# ---------------------------------------------------------------------------
# Group 6: e2e gate routing — awaiting-confirm vs failed vs passed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gate_routes_e2e_awaiting_confirmation_to_pause():
    """Cases generated but not yet confirmed/executed → pause at e2e (no
    rollback to the code worker — the TODO fix)."""
    state = _make_state(
        manager_next="e2e",
        e2e_user_confirmed=False,
        e2e_test_cases=[
            {"id": "tc-r01-1", "requirement_id": "R-01", "scenario": "页面加载", "steps": []},
        ],
        e2e_test_cases_md="# E2E 测试用例",
    )
    out = await manager_gate(state)
    assert out["manager_next"] == "e2e"
    assert out["manager_verdicts"][-1]["decision"] == "pass"


@pytest.mark.asyncio
async def test_gate_routes_e2e_failed_results_to_code_rollback():
    """Executed results with a real regression → rollback to the code worker."""
    state = _make_state(
        manager_next="e2e",
        e2e_user_confirmed=True,
        e2e_test_cases=[
            {"id": "tc-r01-1", "requirement_id": "R-01", "scenario": "x", "steps": []},
        ],
        e2e_results=[{"case_id": "tc-r01-1", "passed": False, "status": "failed", "error": "boom"}],
        e2e_diagnosis={
            "rollback_case_ids": ["tc-r01-1"],
            "counts": {"expected_broken": 0, "selector_coupled": 0, "real_regression": 1},
        },
        e2e_passed=False,
    )
    out = await manager_gate(state)
    assert out["manager_next"] == "code"
    assert out["manager_verdicts"][-1]["decision"] == "rollback"


@pytest.mark.asyncio
async def test_gate_routes_e2e_passed_to_end():
    state = _make_state(
        manager_next="e2e",
        e2e_user_confirmed=True,
        e2e_results=[{"case_id": "tc-r01-1", "passed": True, "status": "passed"}],
        e2e_passed=True,
    )
    out = await manager_gate(state)
    assert out["manager_next"] == "end"


@pytest.mark.asyncio
async def test_gate_routes_e2e_no_results_to_pause_after_confirmed():
    """Confirmed pass-through before the runner submits results → pause at e2e."""
    state = _make_state(
        manager_next="e2e",
        e2e_user_confirmed=True,
        e2e_test_cases=[
            {"id": "tc-r01-1", "requirement_id": "R-01", "scenario": "x", "steps": []},
        ],
        e2e_results=None,
    )
    out = await manager_gate(state)
    assert out["manager_next"] == "e2e"


def test_run_l1_checks_e2e_skips_requires_browser():
    """6.7: skipped requires_browser cases are not failures."""
    results = [
        {"case_id": "tc-a", "passed": True, "status": "passed"},
        {"case_id": "tc-b", "passed": False, "status": "skipped_requires_browser"},
    ]
    assert run_l1_checks(_make_state(e2e_results=results), "e2e") == []


def test_run_l1_checks_e2e_honors_diagnosis_rollback_ids():
    """6.4: expected_broken failures (not in rollback_case_ids) do not fail L1."""
    results = [
        {"case_id": "tc-eb", "passed": False, "status": "failed", "error": "assert"},
        {"case_id": "tc-rr", "passed": False, "status": "failed", "error": "assert"},
    ]
    diagnosis = {"rollback_case_ids": ["tc-rr"]}
    state = _make_state(e2e_results=results, e2e_diagnosis=diagnosis)
    errors = run_l1_checks(state, "e2e")
    # only the real-regression case counts (expected_broken does not fail L1)
    assert len(errors) == 1 and "1" in errors[0]

    # without a diagnosis → legacy semantics: every failed case counts
    state2 = _make_state(e2e_results=results)
    assert len(run_l1_checks(state2, "e2e")) == 1


def test_run_l1_checks_e2e_all_expected_broken_not_failure():
    """C1: 诊断存在且 rollback_case_ids 为空（全预期失效/选择器耦合）→
    失败用例不判失败 —— 空 rollback 列表不能回退到「全部算失败」语义。"""
    results = [{"case_id": "tc-eb", "passed": False, "status": "failed", "error": "assert"}]
    diagnosis = {"rollback_case_ids": [], "counts": {"expected_broken": 1}}
    assert run_l1_checks(
        _make_state(e2e_results=results, e2e_diagnosis=diagnosis), "e2e"
    ) == []


@pytest.mark.asyncio
async def test_gate_all_expected_broken_routes_to_end():
    """C1: 全预期失效一轮 → gate 通过（无真实回归）→ END，不回退 code。"""
    state = _make_state(
        manager_next="e2e",
        e2e_user_confirmed=True,
        e2e_test_cases=[{"id": "tc-eb", "requirement_id": "R-01", "scenario": "x", "steps": []}],
        e2e_results=[{"case_id": "tc-eb", "passed": False, "status": "failed", "error": "assert"}],
        e2e_diagnosis={
            "rollback_case_ids": [],
            "counts": {"expected_broken": 1, "selector_coupled": 0, "real_regression": 0},
        },
        e2e_passed=True,
    )
    out = await manager_gate(state)
    assert out["manager_next"] == "end"
    assert out["manager_verdicts"][-1]["decision"] == "pass"


@pytest.mark.asyncio
async def test_resume_after_e2e_rollback_announces_paused_worker():
    """I2: 真实回归回退 code 后 —— resume_after_e2e 结尾 announce 挂起的
    code worker，前端拿到 human_confirm_required（回退确认），不会卡死。"""
    from app.services.generation.graph import GraphRunner

    runner = GraphRunner()
    state = _make_state(
        analysis_result=PRD_OK,
        design_result=DESIGN_OK,
        code_result=json.dumps({"App.vue": "<template>x</template>"}),
        generated_files={"App.vue": "<template>x</template>"},
    )
    config = {"configurable": {"thread_id": "gen-e2e-rollback-announce"}}
    [ev async for ev in runner.run(state, "gen-e2e-rollback-announce")]
    runner.app.update_state(config, {
        "e2e_user_confirmed": True,
        "e2e_test_cases": [
            {"id": "tc-r01-1", "requirement_id": "R-01", "scenario": "x", "steps": []},
        ],
        "e2e_test_cases_md": "# E2E",
    })

    results = [{
        "case_id": "tc-r01-1", "passed": False, "status": "failed",
        "error": "Assertion failed: expected 第 2 页",
        "evidence": {"dom_snapshot": "<html><body>空白页面</body></html>"},
    }]
    events = [ev async for ev in runner.resume_after_e2e("gen-e2e-rollback-announce", results)]
    types = [e["event_type"] for e in events]
    assert "e2e_diagnosis" in types
    assert "e2e_complete" in types
    confirms = [e for e in events if e["event_type"] == "human_confirm_required"]
    assert confirms and confirms[0]["stage"] == "code"
    assert "未通过" in confirms[0]["data"]["message"]
    snap = runner.app.get_state(config)
    assert snap.values["e2e_passed"] is False
    assert snap.next == ("code",)


@pytest.mark.asyncio
async def test_runner_resume_after_e2e_diagnoser_flow():
    """resume_after_e2e: Test Diagnoser classifies failures; expected-broken
    cases do not fail the run (no code rollback); real regressions do."""
    from app.services.generation.graph import GraphRunner

    runner = GraphRunner()
    state = _make_state(
        analysis_result=PRD_OK,
        design_result=DESIGN_OK,
        code_result=json.dumps({"App.vue": "<template>x</template>"}),
        generated_files={"App.vue": "<template>x</template>"},
    )
    config = {"configurable": {"thread_id": "gen-e2e-diagnose"}}
    events = [ev async for ev in runner.run(state, "gen-e2e-diagnose")]
    assert [e for e in events if e["event_type"] == "human_confirm_required"]

    # seed e2e cases + manifest, confirm, then submit results
    runner.app.update_state(config, {
        "e2e_user_confirmed": True,
        "e2e_test_cases": [
            {"id": "tc-r01-1", "requirement_id": "R-01", "scenario": "分页切换", "steps": []},
        ],
        "e2e_test_cases_md": "# E2E",
        "change_manifest": {"changed_requirements": ["R-01"]},
    })

    # (1) expected_broken failure (manifest declares the change) → e2e passes
    results = [
        {"case_id": "tc-r01-1", "passed": False, "status": "failed",
         "error": "Assertion failed: expected 第 2 页", "evidence": {"dom_snapshot": "<html/>"}},
    ]
    events = [ev async for ev in runner.resume_after_e2e("gen-e2e-diagnose", results)]
    types = [e["event_type"] for e in events]
    assert "e2e_diagnosis" in types
    diag_ev = next(e for e in events if e["event_type"] == "e2e_diagnosis")
    assert diag_ev["data"]["rollback_case_ids"] == []
    complete = next(e for e in events if e["event_type"] == "e2e_complete")
    assert complete["data"]["passed"] is True
    snap = runner.app.get_state(config)
    assert snap.values["e2e_passed"] is True

    # (2) real regression (no manifest match) → e2e fails → rollback to code
    runner.app.update_state(config, {
        "e2e_results": None,
        "e2e_passed": False,
        "e2e_diagnosis": None,
        "change_manifest": {"changed_requirements": ["R-99"]},
    })
    results2 = [
        {"case_id": "tc-r01-1", "passed": False, "status": "failed",
         "error": "Assertion failed: expected 第 2 页",
         "evidence": {"dom_snapshot": "<html><body>空页面</body></html>"}},
    ]
    events2 = [ev async for ev in runner.resume_after_e2e("gen-e2e-diagnose", results2)]
    diag_ev2 = next(e for e in events2 if e["event_type"] == "e2e_diagnosis")
    assert diag_ev2["data"]["rollback_case_ids"] == ["tc-r01-1"]
    complete2 = next(e for e in events2 if e["event_type"] == "e2e_complete")
    assert complete2["data"]["passed"] is False
    snap2 = runner.app.get_state(config)
    assert snap2.values["e2e_passed"] is False
    assert snap2.values["failure_details"]["rollback_target"] == "code"
    # (gate routing of a real-regression run back to the code worker + the
    # paused-worker announcement are covered by
    # test_resume_after_e2e_rollback_announces_paused_worker)


@pytest.mark.asyncio
async def test_runner_resume_after_e2e_skipped_cases_pass():
    """6.7: skipped requires_browser cases never fail the run."""
    from app.services.generation.graph import GraphRunner

    runner = GraphRunner()
    state = _make_state(
        analysis_result=PRD_OK,
        design_result=DESIGN_OK,
        code_result=json.dumps({"App.vue": "<template>x</template>"}),
        generated_files={"App.vue": "<template>x</template>"},
    )
    config = {"configurable": {"thread_id": "gen-e2e-skip"}}
    [ev async for ev in runner.run(state, "gen-e2e-skip")]
    runner.app.update_state(config, {
        "e2e_user_confirmed": True,
        "e2e_test_cases": [
            {"id": "tc-r01-1", "requirement_id": "R-01", "scenario": "多页面流转",
             "steps": [], "requires_browser": True},
        ],
    })
    results = [
        {"case_id": "tc-r01-1", "passed": False, "status": "skipped_requires_browser",
         "error": "requires_browser：待人工/后端浏览器执行"},
    ]
    events = [ev async for ev in runner.resume_after_e2e("gen-e2e-skip", results)]
    complete = next(e for e in events if e["event_type"] == "e2e_complete")
    assert complete["data"]["passed"] is True
    assert complete["data"]["failed_count"] == 0
    assert runner.app.get_state(config).values["e2e_passed"] is True
