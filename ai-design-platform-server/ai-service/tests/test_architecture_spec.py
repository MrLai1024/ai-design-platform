"""Tests for the architecture Spec (task group 4) — dual-product design node.

Covers 4.2 (MD + machine-readable Spec, schema-validated with one redo),
4.3 (L1 field-completeness at the gate), 4.4 (L2 Spec↔PRD coverage via the
Manager LLM, fail-closed), and 4.5 (Spec persisted to
``.ai-memory/spec/architecture.json`` after the gate passes). All LLM calls go
through the ``llm_fn`` seam or a patched ``_llm_generate`` — no real LLM.
"""

import json
import os

import pytest
from unittest.mock import AsyncMock, patch

from app.services.generation.graph import GraphRunner
from app.services.generation.harness import EvalHarness
from app.services.generation.manager import (
    design_gate_feedback,
    evaluate_stage_l2,
    manager_gate,
    record_verdict,
    run_l1_checks,
    run_l2_checks,
)
from app.services.generation.nodes import generate_architecture_spec
from app.services.generation.spec_schema import validate_spec

PRD = (
    "# 需求规格文档\n\n"
    "## 2. 功能模块\n- 用户管理\n- 订单管理\n\n"
    "## 3. 页面结构\n- 用户列表页\n- 订单列表页\n"
)
DESIGN_MD = "# 设计方案\n组件树结构\n数据流设计\n样式方案\n文件拆分方案\n关键实现要点"
VALID_SPEC = {
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
INVALID_SPEC = {k: v for k, v in VALID_SPEC.items() if k != "directory_tree"}


def _make_state(**overrides) -> dict:
    state = {
        "requirement": "生成一个用户管理页面",
        "component_lib": "element-plus",
        "messages": [{"role": "user", "content": "生成一个用户管理页面"}],
        "requirements_state_json": None,
        "analysis_result": PRD,
        "design_result": None,
        "architecture_spec": None,
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
        "stage_phase": "generating",
        "design_doc": None,
        "generated_files": {},
        "compile_errors": None,
        "e2e_test_cases_md": None,
        "e2e_user_confirmed": False,
        "dispatch_contract": None,
        "manager_verdicts": [],
    }
    state.update(overrides)
    return state


def _design_state(spec=None, **overrides) -> dict:
    return _make_state(
        design_result=DESIGN_MD,
        design_doc=DESIGN_MD,
        architecture_spec=spec if spec is not None else dict(VALID_SPEC),
        **overrides,
    )


# ── 4.2 generate_architecture_spec ──


@pytest.mark.asyncio
async def test_generate_spec_valid_first_shot():
    fake = AsyncMock(return_value=json.dumps(VALID_SPEC, ensure_ascii=False))
    spec, errors = await generate_architecture_spec(PRD, state=_make_state(), llm_fn=fake)
    assert errors == []
    assert spec == VALID_SPEC
    fake.assert_awaited_once()


@pytest.mark.asyncio
async def test_generate_spec_default_seam_uses_thinking_off():
    """The singleton default path (llm_fn=None) runs the structured call with
    thinking off — the Spec is a pure JSON contract (4.2)."""
    with patch(
        "app.services.generation.nodes._llm_generate",
        new_callable=AsyncMock,
        return_value=json.dumps(VALID_SPEC, ensure_ascii=False),
    ) as mock_llm:
        spec, errors = await generate_architecture_spec(PRD, state=_make_state())
        assert errors == []
        assert spec == VALID_SPEC
        assert mock_llm.await_args.kwargs["enable_thinking"] is False


@pytest.mark.asyncio
async def test_generate_spec_redo_once_with_validation_errors():
    fake = AsyncMock(side_effect=[
        json.dumps(INVALID_SPEC, ensure_ascii=False),   # 1st attempt: missing directory_tree
        json.dumps(VALID_SPEC, ensure_ascii=False),     # 2nd attempt: fixed
    ])
    spec, errors = await generate_architecture_spec(PRD, state=_make_state(), llm_fn=fake)
    assert errors == []
    assert spec == VALID_SPEC
    # exactly one redo — the validation error fed back into the 2nd prompt
    assert fake.await_count == 2
    second_prompt = fake.await_args.args[1]
    assert "directory_tree" in second_prompt


@pytest.mark.asyncio
async def test_generate_spec_redo_once_then_still_invalid():
    fake = AsyncMock(return_value=json.dumps(INVALID_SPEC, ensure_ascii=False))
    spec, errors = await generate_architecture_spec(PRD, state=_make_state(), llm_fn=fake)
    assert errors != []
    assert any("directory_tree" in e for e in errors)
    # retried exactly once (max_attempts=2), then the gate decides
    assert fake.await_count == 2
    # the retained spec is the last attempt — the merge schema fills the
    # missing key with an empty default, so L1 reports the real gap
    assert validate_spec(spec) != []
    assert spec["directory_tree"] == {}


@pytest.mark.asyncio
async def test_generate_spec_consumes_clarification_products():
    calls = []

    async def fake(system_prompt, user_prompt):
        calls.append(user_prompt)
        return json.dumps(VALID_SPEC, ensure_ascii=False)

    state = _make_state(
        requirements_state_json='{"vision": {"project_name": "后台"}}',
        brainstorm_decisions=[{"topic": "技术选型", "choice": "element-plus", "reason": "用户选择"}],
        brainstorm_assumptions=[{"item_id": "a1", "topic": "数据来源", "assumption": "本地 mock"}],
    )
    spec, errors = await generate_architecture_spec(PRD, state=state, llm_fn=fake)
    assert errors == []
    prompt = calls[0]
    assert "结构化需求" in prompt
    assert "决策日志" in prompt
    assert "假设清单" in prompt


@pytest.mark.asyncio
async def test_generate_spec_feedback_block_in_prompt():
    """Redo feedback (review fix 1) lands in the Spec generation prompt."""
    calls = []

    async def fake(system_prompt, user_prompt):
        calls.append(user_prompt)
        return json.dumps(VALID_SPEC, ensure_ascii=False)

    spec, errors = await generate_architecture_spec(
        PRD, state=_make_state(), llm_fn=fake,
        feedback="L2：订单管理（PRD 声明，Spec 无对应）",
    )
    assert errors == []
    assert "把关反馈" in calls[0]
    assert "订单管理" in calls[0]


# ── 4.3 L1 completeness at the gate ──


def test_l1_catches_missing_spec_fields():
    state = _design_state(spec=INVALID_SPEC)
    errors = run_l1_checks(state, "design")
    assert any("directory_tree" in e for e in errors)

    # a fully-valid dual product passes L1
    assert run_l1_checks(_design_state(), "design") == []


def test_harness_spec_check_deterministic():
    assert EvalHarness.spec_has_required_fields(VALID_SPEC).passed
    assert not EvalHarness.spec_has_required_fields(INVALID_SPEC).passed
    assert not EvalHarness.spec_has_required_fields(None).passed
    assert EvalHarness.validate(_design_state(), "design").passed
    assert not EvalHarness.validate(_design_state(spec=INVALID_SPEC), "design").passed


@pytest.mark.asyncio
async def test_l1_failure_skips_l2_and_evidences_redo():
    fake = AsyncMock()
    state = _design_state(spec=INVALID_SPEC)
    decision, reason, evidence, missing = await evaluate_stage_l2(state, "design", fake)
    assert decision == "redo"
    assert "directory_tree" in reason
    assert evidence
    assert missing == []
    fake.assert_not_awaited()  # L2 is never reached on L1 failure


# ── 4.4 L2 Spec ↔ PRD coverage (Manager LLM) ──


@pytest.mark.asyncio
async def test_l2_parses_missing_list():
    calls = []

    async def fake(system_prompt, user_prompt):
        calls.append(user_prompt)
        return json.dumps({
            "passed": False,
            "missing": [{"feature": "订单管理", "evidence": "PRD 第 2 节声明，Spec pages 无对应页面"}],
        }, ensure_ascii=False)

    result = await run_l2_checks("design", _design_state(), fake)
    assert result["passed"] is False
    assert result["missing"] == [
        {"feature": "订单管理", "evidence": "PRD 第 2 节声明，Spec pages 无对应页面"},
    ]
    # the Manager's judgment input carries PRD + Spec
    assert "订单管理" in calls[0]
    assert "architecture_spec" not in calls[0] and "directory_tree" in calls[0]


@pytest.mark.asyncio
async def test_l2_pass():
    fake = AsyncMock(return_value='{"passed": true, "missing": []}')
    result = await run_l2_checks("design", _design_state(), fake)
    assert result["passed"] is True
    assert result["missing"] == []


@pytest.mark.asyncio
async def test_l2_fail_closed_on_llm_error():
    """Both attempts fail → fail-closed (one retry was consumed)."""
    fake = AsyncMock(side_effect=RuntimeError("provider down"))
    result = await run_l2_checks("design", _design_state(), fake)
    assert result["passed"] is False
    assert result["missing"] == []
    assert result["reason"] == "L2 评估失败"
    assert fake.await_count == 2


@pytest.mark.asyncio
async def test_l2_retries_once_then_uses_result():
    """Review fix 3: a transient LLM error is retried once; the second call's
    result decides the gate (no forced design regeneration on a flake)."""
    calls = []

    async def flaky(system_prompt, user_prompt):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("provider flake")
        return '{"passed": true, "missing": []}'

    result = await run_l2_checks("design", _design_state(), flaky)
    assert result["passed"] is True
    assert result["missing"] == []
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_l2_fail_closed_on_unparsable_output():
    fake = AsyncMock(return_value="这不是 JSON")
    result = await run_l2_checks("design", _design_state(), fake)
    assert result["passed"] is False
    assert result["reason"] == "L2 评估失败"


@pytest.mark.asyncio
async def test_l2_fail_closed_when_not_passed_without_missing():
    """{"passed": false, "missing": []} → fail-closed (review minor 5): the
    Manager judged against the Spec but gave no missing list — the gate must
    not pass an unverifiable Spec on a bare "no"."""
    fake = AsyncMock(return_value='{"passed": false, "missing": []}')
    result = await run_l2_checks("design", _design_state(), fake)
    assert result["passed"] is False
    assert result["missing"] == []
    assert result["reason"] == "L2 评估失败"


@pytest.mark.asyncio
async def test_changed_spec_invalidates_reused_design_verdict():
    """Review minor 6: the design verdict signature covers the Spec — a
    Spec-only change re-judges instead of reusing a stale verdict."""
    state = _design_state()  # design_result + VALID_SPEC
    record_verdict(state, "design", "pass", "")
    fake = AsyncMock(return_value='{"passed": true, "missing": []}')

    # unchanged output → verdict reused, no LLM call
    out = await manager_gate(state, fake)
    assert len(out["manager_verdicts"]) == 1
    fake.assert_not_awaited()

    # Spec changed (MD identical) → signature differs → re-judged (L2 runs)
    changed = _design_state(spec={
        **VALID_SPEC,
        "pages": [{"id": "p-99", "name": "新页面", "interactions": [], "data": []}],
    })
    changed["manager_verdicts"] = list(state["manager_verdicts"])
    out2 = await manager_gate(changed, fake)
    assert len(out2["manager_verdicts"]) == 2
    assert out2["manager_verdicts"][-1]["decision"] == "pass"
    fake.assert_awaited()


@pytest.mark.asyncio
async def test_l2_trivially_passes_other_stages():
    fake = AsyncMock()
    for stage in ("analysis", "code", "e2e"):
        result = await run_l2_checks(stage, _make_state(), fake)
        assert result["passed"] is True
    fake.assert_not_awaited()


@pytest.mark.asyncio
async def test_evaluate_stage_l2_design_pass():
    fake = AsyncMock(return_value='{"passed": true, "missing": []}')
    decision, reason, evidence, missing = await evaluate_stage_l2(_design_state(), "design", fake)
    assert decision == "pass"
    assert reason == ""
    assert evidence == []
    assert missing == []


@pytest.mark.asyncio
async def test_evaluate_stage_l2_design_missing_surfaces_in_verdict_and_diagnosis():
    fake = AsyncMock(return_value=json.dumps({
        "passed": False,
        "missing": [{"feature": "订单管理", "evidence": "PRD 声明，Spec 无对应"}],
    }, ensure_ascii=False))
    state = _design_state()
    decision, reason, evidence, missing = await evaluate_stage_l2(state, "design", fake)
    assert decision == "redo"
    assert "订单管理" in reason
    assert any("订单管理" in e for e in evidence)
    assert missing == [{"feature": "订单管理", "evidence": "PRD 声明，Spec 无对应"}]

    # the manual gate streams the missing list on the verdict + diagnosis card
    runner = GraphRunner()
    events = await runner._gate_manual_stage(state, "design", llm_fn=fake)
    assert events[0]["data"]["decision"] == "redo"
    assert events[0]["data"]["missing"] == [
        {"feature": "订单管理", "evidence": "PRD 声明，Spec 无对应"},
    ]
    card = events[1]
    assert card["data"]["card"] == "diagnosis_card"
    assert card["data"]["data"]["missing"] == [
        {"feature": "订单管理", "evidence": "PRD 声明，Spec 无对应"},
    ]
    assert "订单管理" in card["data"]["content"]


# ── 4.2/4.5 phase-2 integration (GraphRunner.run) ──


@pytest.mark.asyncio
async def test_phase2_dual_product_and_gate_pass():
    """Phase 2 streams the MD, generates the Spec, gates L1+L2 pass, and
    records a pass verdict — the flow then pauses for human confirmation."""
    with patch(
        "app.services.generation.nodes._llm_generate",
        new_callable=AsyncMock,
        return_value=DESIGN_MD,
    ):
        fake = AsyncMock(side_effect=[
            json.dumps(VALID_SPEC, ensure_ascii=False),      # Spec generation
            '{"passed": true, "missing": []}',               # L2 gate
        ])
        runner = GraphRunner(llm_fn=fake)
        state = _make_state()
        events = [ev async for ev in runner.run(state, "gen-spec-pass")]

    assert state["design_result"] == DESIGN_MD
    assert state["architecture_spec"] == VALID_SPEC
    assert state["dispatch_contract"]["task_id"] == "design"
    verdicts = state["manager_verdicts"]
    assert verdicts[-1]["node"] == "design"
    assert verdicts[-1]["decision"] == "pass"

    types = [e["event_type"] for e in events]
    assert "human_confirm_required" in types
    gate_event = next(e for e in events if e["event_type"] == "manager_verdict")
    assert gate_event["data"]["decision"] == "pass"


@pytest.mark.asyncio
async def test_phase2_invalid_spec_gate_fails_after_one_redo():
    """An invalid Spec is retried once (2 spec calls), then the gate fails L1 —
    L2 is never reached and the verdict is redo."""
    with patch(
        "app.services.generation.nodes._llm_generate",
        new_callable=AsyncMock,
        return_value=DESIGN_MD,
    ):
        fake = AsyncMock(side_effect=[
            json.dumps(INVALID_SPEC, ensure_ascii=False),
            json.dumps(INVALID_SPEC, ensure_ascii=False),
        ])
        runner = GraphRunner(llm_fn=fake)
        state = _make_state()
        events = [ev async for ev in runner.run(state, "gen-spec-fail")]

    # both spec attempts were consumed; L2 gate never ran
    assert fake.await_count == 2
    verdicts = state["manager_verdicts"]
    assert verdicts[-1]["node"] == "design"
    assert verdicts[-1]["decision"] == "redo"
    assert "directory_tree" in verdicts[-1]["reason"]
    gate_event = next(e for e in events if e["event_type"] == "manager_verdict")
    assert gate_event["data"]["decision"] == "redo"
    card = next(e for e in events if e["event_type"] == "manager_message")
    assert card["data"]["card"] == "diagnosis_card"
    assert any("directory_tree" in e for e in card["data"]["data"]["evidence"])


@pytest.mark.asyncio
async def test_phase2_l2_failure_gate_fails_with_missing_list():
    """L1 passes but L2 finds missing PRD features → redo with the missing
    list as the diagnosis content."""
    with patch(
        "app.services.generation.nodes._llm_generate",
        new_callable=AsyncMock,
        return_value=DESIGN_MD,
    ):
        fake = AsyncMock(side_effect=[
            json.dumps(VALID_SPEC, ensure_ascii=False),      # Spec generation
            json.dumps({"passed": False, "missing": [
                {"feature": "订单管理", "evidence": "PRD 声明，Spec 无对应"},
            ]}, ensure_ascii=False),                          # L2 gate
        ])
        runner = GraphRunner(llm_fn=fake)
        state = _make_state()
        events = [ev async for ev in runner.run(state, "gen-spec-l2fail")]

    verdicts = state["manager_verdicts"]
    assert verdicts[-1]["decision"] == "redo"
    assert "订单管理" in verdicts[-1]["reason"]
    gate_event = next(e for e in events if e["event_type"] == "manager_verdict")
    assert gate_event["data"]["missing"] == [
        {"feature": "订单管理", "evidence": "PRD 声明，Spec 无对应"},
    ]
    card = next(e for e in events if e["event_type"] == "manager_message")
    assert card["data"]["card"] == "diagnosis_card"
    assert card["data"]["data"]["missing"][0]["feature"] == "订单管理"


@pytest.mark.asyncio
async def test_phase2_spec_written_to_memory_on_pass(tmp_path, monkeypatch):
    """4.5: once the design gate passes, the Spec lands in
    ``<project_root>/.ai-memory/spec/architecture.json`` (7.1: persistent
    ``data/generated/<app_id>/`` root replaces the tempfile root)."""
    monkeypatch.setenv("AI_GEN_DATA_DIR", str(tmp_path))
    with patch(
        "app.services.generation.nodes._llm_generate",
        new_callable=AsyncMock,
        return_value=DESIGN_MD,
    ):
        fake = AsyncMock(side_effect=[
            json.dumps(VALID_SPEC, ensure_ascii=False),
            '{"passed": true, "missing": []}',
        ])
        runner = GraphRunner(llm_fn=fake)
        state = _make_state()
        events = [ev async for ev in runner.run(state, "gen-spec-mem")]

    assert any(e["event_type"] == "human_confirm_required" for e in events)
    candidates = [
        os.path.join(root, f) for root, _dirs, files in os.walk(tmp_path / "generated")
        for f in files
    ]
    spec_candidates = [c for c in candidates if c.endswith("architecture.json")]
    assert len(spec_candidates) == 1
    assert spec_candidates[0].endswith(os.path.join(".ai-memory", "spec", "architecture.json"))
    with open(spec_candidates[0], encoding="utf-8") as f:
        assert json.load(f) == VALID_SPEC
    # 7.3: 同一份 Spec 不维护第二套格式; 4.5 后 index 标记 design 完成。
    assert (tmp_path / "generated").is_dir()


@pytest.mark.asyncio
async def test_phase2_failed_gate_does_not_write_spec(tmp_path, monkeypatch):
    """No Spec write when the gate does not pass (7.3: 把关裁决/决策日志仍留痕,
    architecture.json 绝不落盘 — 失败版 Spec 不污染应用记忆)."""
    monkeypatch.setenv("AI_GEN_DATA_DIR", str(tmp_path))
    with patch(
        "app.services.generation.nodes._llm_generate",
        new_callable=AsyncMock,
        return_value=DESIGN_MD,
    ):
        fake = AsyncMock(side_effect=[
            json.dumps(INVALID_SPEC, ensure_ascii=False),
            json.dumps(INVALID_SPEC, ensure_ascii=False),
        ])
        runner = GraphRunner(llm_fn=fake)
        state = _make_state()
        events = [ev async for ev in runner.run(state, "gen-spec-nomem")]

    assert state["manager_verdicts"][-1]["decision"] == "redo"
    generated = tmp_path / "generated"
    if generated.exists():
        spec_files = [
            os.path.join(root, f)
            for root, _dirs, files in os.walk(generated)
            for f in files if f.endswith("architecture.json")
        ]
        assert spec_files == []


@pytest.mark.asyncio
async def test_phase2_design_redo_resume_reruns_phase2_with_feedback():
    """Review fix 1: a design redo verdict clears the dual product, so the
    resume path re-runs phase 2 — with the L2 missing list fed back into the
    MD and Spec prompts — instead of advancing to code with the failed Spec.
    A passing second gate then proceeds normally."""
    md_calls = []

    async def fake_md(system_prompt, user_content, **kwargs):
        md_calls.append(user_content)
        return DESIGN_MD

    llm_calls = []

    async def fake(system_prompt, user_prompt):
        llm_calls.append((system_prompt, user_prompt))
        if len(llm_calls) == 1:
            return json.dumps(VALID_SPEC, ensure_ascii=False)             # run 1: Spec
        if len(llm_calls) == 2:
            return json.dumps({"passed": False, "missing": [
                {"feature": "订单管理", "evidence": "PRD 声明，Spec 无对应"},
            ]}, ensure_ascii=False)                                       # run 1: L2 → redo
        if len(llm_calls) == 3:
            # task group 9: 恢复阶梯的失败分类 (L2 缺失清单 → LLM 判断 drift)。
            return '{"category": "drift", "reason": "Spec 遗漏需求功能点 订单管理", "scope_change": {"required": false, "note": ""}}'
        if len(llm_calls) == 4:
            return json.dumps(VALID_SPEC, ensure_ascii=False)             # run 2: Spec
        return '{"passed": true, "missing": []}'                          # run 2: L2 → pass

    with patch("app.services.generation.nodes._llm_generate", new=fake_md):
        runner = GraphRunner(llm_fn=fake)
        state = _make_state()
        events1 = [ev async for ev in runner.run(state, "gen-redo-loop")]

        # run 1: redo verdict → dual product cleared, flow paused, no code phase
        assert state["manager_verdicts"][-1]["node"] == "design"
        assert state["manager_verdicts"][-1]["decision"] == "redo"
        assert "订单管理" in state["manager_verdicts"][-1]["reason"]
        assert state["design_result"] is None
        assert state["design_doc"] is None
        assert state["architecture_spec"] is None
        assert any(e["event_type"] == "human_confirm_required" for e in events1)
        assert not any(e["stage"] == "code" for e in events1)

        # resume: phase 2 re-runs with the gate feedback → gate passes
        events2 = [ev async for ev in runner.resume("gen-redo-loop")]
    assert state["design_result"] == DESIGN_MD
    assert state["architecture_spec"] == VALID_SPEC
    assert state["manager_verdicts"][-1]["decision"] == "pass"
    # the redo reason (missing list) was fed back into both regenerations
    assert "把关反馈" in md_calls[1]
    assert "订单管理" in md_calls[1]
    # 9.1/9.2: 重派反馈携带失败分类 + 历史策略 (llm_calls[3] 是 run-2 Spec;
    # llm_calls[2] 是恢复阶梯的分类调用)。
    assert "把关反馈" in llm_calls[3][1]
    assert "订单管理" in llm_calls[3][1]
    assert "失败分类" in llm_calls[3][1]
    assert any(e["event_type"] == "human_confirm_required" for e in events2)
    assert not any(e["stage"] == "code" for e in events2)


@pytest.mark.asyncio
async def test_phase3_blocked_until_design_passes():
    """Defense in depth (review fix 1): stale design outputs with a redo
    verdict block the code phase and get cleared — never advanced on."""
    runner = GraphRunner()
    state = _make_state(
        design_result=DESIGN_MD,
        design_doc=DESIGN_MD,
        architecture_spec=dict(VALID_SPEC),
        manager_verdicts=[
            {"node": "design", "decision": "redo",
             "reason": "L2：订单管理（PRD 声明，Spec 无对应）",
             "signature": "s1", "at": "t"},
        ],
    )
    events = [ev async for ev in runner.run(state, "gen-phase3-guard")]

    assert any(e["event_type"] == "error" and e["stage"] == "design" for e in events)
    assert state["design_result"] is None
    assert state["architecture_spec"] is None
    assert not any(e["stage"] == "code" for e in events)


def test_design_gate_feedback_helper():
    """design_gate_feedback returns the last design redo reason (and only
    then) — the regeneration prompts consume it."""
    base = _design_state()
    assert design_gate_feedback(base) == ""
    state = _design_state(manager_verdicts=[
        {"node": "design", "decision": "redo", "reason": "L2：订单管理（缺少）",
         "signature": "s1", "at": "t"},
    ])
    assert design_gate_feedback(state) == "L2：订单管理（缺少）"
    passed = _design_state(manager_verdicts=[
        {"node": "design", "decision": "redo", "reason": "L2：订单管理（缺少）",
         "signature": "s1", "at": "t"},
        {"node": "design", "decision": "pass", "reason": "", "signature": "s2", "at": "t"},
    ])
    assert design_gate_feedback(passed) == ""
