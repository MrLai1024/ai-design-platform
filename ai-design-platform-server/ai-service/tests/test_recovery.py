"""Tests for task group 9: problem recovery & self-closing loop.

Covers: 9.1 failure classification (deterministic-first + LLM + fail-safe),
9.2 recovery ladder decisions (redispatch → split → rollback → escalate),
9.3 red lines (≤2 autonomous rounds per problem → 求援; scope change →
confirm_card), 9.4 LoopControl through the ladder (per-node/global/
no-improvement), 9.5 problems.jsonl + memory_db persistence and reuse.
"""

import json

import pytest

from app.services.generation.recovery import (
    RESCUE_OPTIONS,
    SCOPE_OPTIONS,
    build_recovery_feedback,
    bump_problem_attempts,
    choose_strategy,
    classify_failure,
    consume_escalation_reset,
    consume_scope_confirmation,
    history_strategies_block,
    red_line_hit,
    rejects_scope_change,
    reset_problem_attempts,
    resolve_recovery_outcomes,
    retrieve_fix_strategies,
    run_recovery,
    split_instruction_block,
)
from app.services.generation.verifier import evidence_signature

PRD_OK = (
    "# 需求规格文档\n\n"
    "## 1. 功能概述\n...\n\n"
    "## 2. 功能模块\n- 用户管理\n\n"
    "## 3. 页面结构\n- 用户列表页\n\n"
    "## 4. 数据模型\n\n## 5. 交互行为\n"
)
DESIGN_OK = "# 设计方案\n组件树结构\n数据流设计\n样式方案\n文件拆分方案\n关键实现要点"
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
COMPILE_EVIDENCE = {"compile_errors": [{"file": "A.vue", "line": 1, "message": "syntax"}]}


def _state(**overrides) -> dict:
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
        "generation_id": "gen-rec-test",
        "user_id": "u-test",
    }
    state.update(overrides)
    return state


def _code_state(files=None, compile_errors=None, **overrides) -> dict:
    files = files if files is not None else {"App.vue": "<template>x</template>"}
    return _state(
        code_result=json.dumps(files, ensure_ascii=False),
        generated_files=files,
        compile_errors=compile_errors,
        **overrides,
    )


# ---------------------------------------------------------------------------
# 9.1 失败分类: 确定性优先 (zero-LLM)
# ---------------------------------------------------------------------------


class TestClassifyDeterministic:
    @pytest.mark.asyncio
    async def test_compile_errors_classify_compile(self):
        cls = await classify_failure(_state(), node="code", evidence=COMPILE_EVIDENCE)
        assert cls["category"] == "compile"
        assert cls["confidence"] == "high"
        assert cls["signature"] and cls["output_signature"]
        assert "编译" in cls["reason"]

    @pytest.mark.asyncio
    async def test_contract_violations_classify_contradiction(self):
        evidence = {"contract_violations": [{"type": "verify_error", "file": "B.vue", "detail": "x"}]}
        cls = await classify_failure(_state(), node="code", evidence=evidence)
        assert cls["category"] == "contradiction"
        assert cls["confidence"] == "high"

    @pytest.mark.asyncio
    async def test_llm_error_hint(self):
        cls = await classify_failure(_state(), node="design", hint="llm_error")
        assert cls["category"] == "llm_error"
        assert cls["confidence"] == "high"

    @pytest.mark.asyncio
    async def test_format_invalid_design_spec_fields(self):
        cls = await classify_failure(_state(), node="design", reason="字段 spec_version 缺失或为空")
        assert cls["category"] == "format_invalid"
        assert cls["confidence"] == "high"

    @pytest.mark.asyncio
    async def test_format_invalid_code_empty(self):
        cls = await classify_failure(_state(), node="code", reason="Generated code is empty")
        assert cls["category"] == "format_invalid"

    @pytest.mark.asyncio
    async def test_no_convergence_repeated_signature(self):
        """证据签名在修复轮中重复 → no_convergence (优先于类别细分)."""
        sig = evidence_signature(COMPILE_EVIDENCE)
        state = _state(debugger_rounds=[{"round": 1, "signature": sig, "diagnosis": {}}])
        cls = await classify_failure(state, node="code", evidence=COMPILE_EVIDENCE)
        assert cls["category"] == "no_convergence"
        assert cls["confidence"] == "high"

    @pytest.mark.asyncio
    async def test_loop_control_blocked_hint(self):
        cls = await classify_failure(_state(), node="e2e", hint="loop_control_blocked")
        assert cls["category"] == "no_convergence"

    @pytest.mark.asyncio
    async def test_state_compile_errors_fallback(self):
        """无 verifier 证据时 state.compile_errors 兜底 (phase-3 legacy)."""
        cls = await classify_failure(
            _state(compile_errors=[{"file": "A.vue", "line": 1, "message": "syntax"}]), node="code"
        )
        assert cls["category"] == "compile"


# ---------------------------------------------------------------------------
# 9.1 失败分类: LLM 路径 + fail-safe
# ---------------------------------------------------------------------------


class TestClassifyLLM:
    @pytest.mark.asyncio
    async def test_llm_classifies_design_missing_drift(self):
        async def fake_llm(_system, _user):
            return '{"category": "drift", "reason": "Spec 遗漏功能点 订单管理", "scope_change": {"required": false, "note": ""}}'

        cls = await classify_failure(
            _state(analysis_result=PRD_OK), node="design",
            reason="L2：订单管理（PRD 声明，Spec 无对应）",
            missing=[{"feature": "订单管理", "evidence": "PRD 声明"}],
            llm_fn=fake_llm,
        )
        assert cls["category"] == "drift"
        assert cls["confidence"] == "medium"
        assert cls["scope_change"] is False

    @pytest.mark.asyncio
    async def test_llm_fail_safe_heuristic_low(self):
        async def bad_llm(_s, _u):
            raise RuntimeError("no provider")

        cls = await classify_failure(
            _state(), node="design",
            reason="L2：订单管理（PRD 声明，Spec 无对应）",
            missing=[{"feature": "订单管理", "evidence": "PRD 声明"}],
            llm_fn=bad_llm,
        )
        assert cls["category"] == "drift"        # 启发式: 需求↔设计缺口 → 跑偏
        assert cls["confidence"] == "low"

    @pytest.mark.asyncio
    async def test_scope_change_surfaces_from_llm(self):
        async def fake_llm(_s, _u):
            return ('{"category": "drift", "reason": "功能过多", '
                    '"scope_change": {"required": true, "note": "需删减订单模块"}}')

        cls = await classify_failure(
            _state(), node="design",
            reason="L2：…", missing=[{"feature": "订单管理", "evidence": "x"}],
            llm_fn=fake_llm,
        )
        assert cls["scope_change"] is True
        assert cls["scope_change_note"] == "需删减订单模块"


# ---------------------------------------------------------------------------
# 9.2 恢复阶梯决策
# ---------------------------------------------------------------------------


class TestChooseStrategy:
    @staticmethod
    def _cls(category, node="code"):
        return {"node": node, "category": category, "signature": "sig-1"}

    def test_redispatch_first_attempt_compile(self):
        s = choose_strategy(_state(), self._cls("compile"), attempts=1, red_line=False)
        assert s["strategy"] == "redispatch"
        assert s["target"] == "code"

    def test_split_second_attempt_compile(self):
        s = choose_strategy(_state(), self._cls("compile"), attempts=2, red_line=False)
        assert s["strategy"] == "split"
        assert s["target"] == "code"

    def test_contradiction_second_attempt_split(self):
        s = choose_strategy(_state(), self._cls("contradiction"), attempts=2, red_line=False)
        assert s["strategy"] == "split"

    def test_drift_design_redispatch_then_rollback(self):
        s1 = choose_strategy(_state(), self._cls("drift", "design"), attempts=1, red_line=False)
        assert s1["strategy"] == "redispatch"
        assert s1["target"] == "design"
        s2 = choose_strategy(_state(), self._cls("drift", "design"), attempts=2, red_line=False)
        assert s2["strategy"] == "rollback"
        assert s2["target"] == "design"

    def test_e2e_drift_rollbacks_code(self):
        s = choose_strategy(_state(), self._cls("drift", "e2e"), attempts=1, red_line=False)
        assert s["strategy"] == "rollback"
        assert s["target"] == "code"

    def test_no_convergence_escalates(self):
        s = choose_strategy(_state(), self._cls("no_convergence"), attempts=1, red_line=False)
        assert s["strategy"] == "escalate"

    def test_red_line_escalates(self):
        s = choose_strategy(_state(), self._cls("compile"), attempts=3, red_line=True)
        assert s["strategy"] == "escalate"

    def test_llm_error_stays_redispatch(self):
        s = choose_strategy(_state(), self._cls("llm_error"), attempts=2, red_line=False)
        assert s["strategy"] == "redispatch"

    def test_feedback_text_carries_classification(self):
        cls = {"node": "code", "category": "compile", "confidence": "high",
               "reason": "编译失败：1 处错误", "suggested_fix": ""}
        feedback = build_recovery_feedback(cls, {"strategy": "redispatch", "target": "code"})
        assert "重派（带反馈）" in feedback
        assert "编译失败" in feedback
        assert "失败分类" in feedback


# ---------------------------------------------------------------------------
# 9.3 红线: 尝试计数 / 求援 / 范围确认
# ---------------------------------------------------------------------------


class TestRedLineAttempts:
    def test_bump_and_hit_threshold(self):
        state = _state()
        assert bump_problem_attempts(state, "s1") == 1
        assert bump_problem_attempts(state, "s1") == 2
        assert red_line_hit(state, "s1") is False          # 第 2 轮仍自主
        assert bump_problem_attempts(state, "s1") == 3
        assert red_line_hit(state, "s1") is True           # 第 3 轮 → 强制求援

    def test_reset_problem_attempts(self):
        state = _state()
        bump_problem_attempts(state, "s1")
        bump_problem_attempts(state, "s2")
        reset_problem_attempts(state, "s1")
        assert state["problem_attempts"] == {"s2": 1}

    @pytest.mark.asyncio
    async def test_run_recovery_ladder_progression(self):
        """同证据签名: 第 1 轮重派 → 第 2 轮拆分 → 第 3 轮红线求援."""
        state = _state()
        r1 = await run_recovery(state, node="code", decision="redo", reason="编译未通过", evidence=COMPILE_EVIDENCE)
        assert r1["escalate"] is False and r1["attempts"] == 1
        assert r1["strategy"]["strategy"] == "redispatch"
        r2 = await run_recovery(state, node="code", decision="redo", reason="编译未通过", evidence=COMPILE_EVIDENCE)
        assert r2["escalate"] is False and r2["attempts"] == 2
        assert r2["strategy"]["strategy"] == "split"
        r3 = await run_recovery(state, node="code", decision="redo", reason="编译未通过", evidence=COMPILE_EVIDENCE)
        assert r3["escalate"] is True and r3["attempts"] == 3
        assert r3["strategy"]["strategy"] == "escalate"
        assert state["recovery_last"]["escalate"] is True
        assert len(state["recovery_events"]) == 3
        assert [e["result"] for e in state["recovery_events"]] == ["pending", "pending", "escalated"]

    def test_consume_escalation_reset(self):
        """「继续自主」: 清标记 + 重置问题计数 + 重置 LoopControl 计数 +
        清除最近裁决的 escalate 标记 (防 reuse 死循环)."""
        state = _state(
            escalated_signature="s1",
            problem_attempts={"s1": 3},
            rollback_count={"code": 3},
            rollback_records=[{"to_node": "code", "previous_output_hash": "h", "rollback_id": "a"}],
            manager_verdicts=[{"node": "code", "decision": "redo", "recovery": {"escalate": True}}],
        )
        assert consume_escalation_reset(state) is True
        assert "escalated_signature" not in state
        assert state["problem_attempts"] == {}
        assert state["rollback_count"] == {}
        assert state["rollback_records"] == []
        assert state["manager_verdicts"][-1]["recovery"]["escalate"] is False
        assert consume_escalation_reset(state) is False  # 无标记 → no-op

    def test_consume_scope_confirmation(self):
        state = _state(pending_scope_change={"note": "删减订单模块", "node": "design", "signature": "s1"})
        assert consume_scope_confirmation(state) is True
        assert state["scope_change_approved"] == "删减订单模块"
        assert "pending_scope_change" not in state
        # 无待确认项 → 不自我批准
        assert consume_scope_confirmation(_state()) is False

    def test_scope_approval_enters_design_feedback(self):
        from app.services.generation.manager import design_gate_feedback

        state = _state(
            scope_change_approved="删减订单模块",
            manager_verdicts=[{"node": "design", "decision": "redo", "reason": "L2：遗漏", "signature": "s"}],
        )
        feedback = design_gate_feedback(state)
        assert "用户已确认的范围变更" in feedback
        assert "删减订单模块" in feedback

    @pytest.mark.asyncio
    async def test_scope_rejection_on_regen_resume(self):
        """9.3: 范围确认卡「重新生成/取消」→ resume 拒绝范围变更 (不批准);
        普通 resume (确认) → 批准。"""
        from app.services.generation.graph import GraphRunner

        # I5: 精确匹配选项文本, 普通反馈文本含"不要"不误判。
        assert rejects_scope_change("重新生成")
        assert rejects_scope_change("取消")
        assert rejects_scope_change("重新生成一遍")
        assert not rejects_scope_change("不要重复生成整个页面")
        assert not rejects_scope_change("好的")
        runner = GraphRunner()
        config = {"configurable": {"thread_id": "gen-scope-reject"}}
        state = _state(
            analysis_result=PRD_OK,
            design_result=DESIGN_OK,
            architecture_spec=dict(SPEC_OK),
            code_result=json.dumps({"App.vue": "<template>x</template>"}),
            generated_files={"App.vue": "<template>x</template>"},
            e2e_results=[{"case_id": "tc-1", "passed": True, "status": "passed"}],
            e2e_passed=True,
        )
        # 跑到 END (无 LLM), 再补一个待确认范围标记模拟"确认卡后暂停"的 checkpoint。
        [ev async for ev in runner.run(state, "gen-scope-reject")]
        runner.app.update_state(config, {
            "pending_scope_change": {"note": "删减订单模块", "node": "code", "signature": "s1"},
            "manager_next": "end",
        })
        # 「重新生成」反馈 → 拒绝 (不批准)
        [ev async for ev in runner.resume("gen-scope-reject", code_feedback="重新生成")]
        snap = runner.app.get_state(config)
        assert not snap.values.get("pending_scope_change")
        assert not snap.values.get("scope_change_approved")
        # 「确认」路径 (无拒绝反馈) → 批准
        runner.app.update_state(config, {
            "pending_scope_change": {"note": "删减订单模块", "node": "code", "signature": "s1"},
            "manager_next": "end",
        })
        [ev async for ev in runner.resume("gen-scope-reject")]
        snap2 = runner.app.get_state(config)
        assert snap2.values.get("scope_change_approved") == "删减订单模块"
        assert not snap2.values.get("pending_scope_change")


# ---------------------------------------------------------------------------
# 9.4 LoopControl 过阶梯 (gate redo/rollback 路由) + 9.3 gate 级求援
# ---------------------------------------------------------------------------


class TestGateThroughLadder:
    @pytest.mark.asyncio
    async def test_gate_redo_records_rollback_and_feedback(self):
        from app.services.generation.manager import manager_gate

        out = await manager_gate(_code_state(compile_errors=list(COMPILE_EVIDENCE["compile_errors"])))
        assert out["manager_next"] == "code"
        assert out["manager_verdicts"][-1]["decision"] == "redo"
        assert out["rollback_count"] == {"code": 1}
        rec = out["manager_verdicts"][-1]["recovery"]
        assert rec["category"] == "compile"
        assert rec["escalate"] is False
        # 重派反馈 (分类 + 阶梯策略) 进入 verdict reason
        assert "失败分类" in out["manager_verdicts"][-1]["reason"]
        assert "重派" in out["manager_verdicts"][-1]["reason"]
        assert len(out["recovery_events"]) == 1

    @pytest.mark.asyncio
    async def test_gate_red_line_escalates_after_three(self):
        """不同输出、相同证据签名 ×3 → 第 3 次把关红线求援 (不再自主派发)."""
        from app.services.generation.manager import manager_gate

        out = None
        for i in range(3):
            state = _code_state(
                files={f"F{i}.vue": f"<template>{i}</template>"},
                compile_errors=list(COMPILE_EVIDENCE["compile_errors"]),
            )
            if out is not None:
                state["problem_attempts"] = dict(out.get("problem_attempts") or {})
            out = await manager_gate(state)
        assert out["escalated_signature"]
        assert out["needs_manual_review"] is True
        assert out["recovery_last"]["escalate"] is True
        assert out["recovery_last"]["attempts"] == 3

    @pytest.mark.asyncio
    async def test_gate_escalates_on_loop_control_blocked(self):
        """9.4: 单节点回退超限 (3 次) → gate redo 转求援, 不执行 worker.
        I2: 裁决的 recovery.escalate 同步翻转 → 裁决卡路径发射求援卡 (与
        announce 去重后只出现一张)。"""
        from app.services.generation.manager import manager_gate

        out = await manager_gate(_code_state(
            compile_errors=list(COMPILE_EVIDENCE["compile_errors"]),
            rollback_count={"code": 3},
        ))
        assert out["escalated_signature"]
        assert out["needs_manual_review"] is True
        assert out["recovery_last"]["escalate"] is True
        assert out["manager_verdicts"][-1]["recovery"]["escalate"] is True

    @pytest.mark.asyncio
    async def test_gate_escalates_on_no_improvement(self):
        """9.4: 连续两次同节点同哈希回退 → 无改进熔断 → 求援 (裁决卡 escalate)."""
        from app.services.generation.manager import manager_gate

        out = await manager_gate(_code_state(
            compile_errors=list(COMPILE_EVIDENCE["compile_errors"]),
            rollback_records=[
                {"to_node": "code", "previous_output_hash": "h1", "rollback_id": "a"},
                {"to_node": "code", "previous_output_hash": "h1", "rollback_id": "b"},
            ],
        ))
        assert out["escalated_signature"]
        assert out["recovery_last"]["escalate"] is True
        assert out["manager_verdicts"][-1]["recovery"]["escalate"] is True

    @pytest.mark.asyncio
    async def test_manual_gate_red_line_emits_rescue_card(self):
        """9.3 场景: 同一问题自主重试 2 轮仍未通过 → diagnosis_card(求援),
        携带 继续自主/转人工 选项."""
        from app.services.generation.graph import GraphRunner

        runner = GraphRunner()
        state = None
        rescue = []
        for i in range(3):
            state = _code_state(
                files={f"F{i}.vue": f"<template>{i}</template>"},
                compile_errors=list(COMPILE_EVIDENCE["compile_errors"]),
            )
            if i > 0:
                state["problem_attempts"] = prev_attempts
            events = await runner._gate_manual_stage(state, "code")
            prev_attempts = dict(state["problem_attempts"])
            cards = [e["data"] for e in events if e["event_type"] == "manager_message"]
            if i < 2:
                assert not [c for c in cards if c["card"] == "diagnosis_card" and c.get("options")]
            else:
                rescue = [c for c in cards if c["card"] == "diagnosis_card" and c.get("options")]
        assert rescue and rescue[0]["options"] == list(RESCUE_OPTIONS)
        assert state["needs_manual_review"] is True
        assert state["escalated_signature"]

    @pytest.mark.asyncio
    async def test_manual_gate_scope_change_emits_confirm_card(self):
        """9.3 场景: 诊断建议删减功能范围 → confirm_card 请求确认, 不自行删减."""
        from app.services.generation.graph import GraphRunner

        llm_calls = []

        async def fake(system_prompt, user_prompt):
            llm_calls.append((system_prompt, user_prompt))
            if len(llm_calls) == 1:
                return json.dumps({"passed": False, "missing": [
                    {"feature": "订单管理", "evidence": "PRD 声明，Spec 无对应"},
                ]}, ensure_ascii=False)
            return ('{"category": "drift", "reason": "功能过多需删减", '
                    '"scope_change": {"required": true, "note": "需删减订单模块"}}')

        runner = GraphRunner(llm_fn=fake)
        state = _state(
            analysis_result=PRD_OK,
            design_result=DESIGN_OK,
            design_doc=DESIGN_OK,
            architecture_spec=dict(SPEC_OK),
        )
        events = await runner._gate_manual_stage(state, "design")
        cards = [e["data"] for e in events if e["event_type"] == "manager_message"]
        confirm = [c for c in cards if c["card"] == "confirm_card"]
        assert confirm and confirm[0]["options"] == list(SCOPE_OPTIONS)
        assert "订单模块" in confirm[0]["content"]
        assert state["pending_scope_change"]["note"] == "需删减订单模块"
        assert not state.get("escalated_signature")  # 未触红线, 只是范围待确认

    @pytest.mark.asyncio
    async def test_announce_paused_worker_rescue_dedupe(self):
        """I1: 裁决路径已发射求援卡 (verdict.recovery.escalate) → announce 不再
        重复发射, 只补普通确认; 熔断标记无对应裁决卡时才在这里发射求援卡。"""
        from app.services.generation.graph import GraphRunner

        runner = GraphRunner()
        config = {"configurable": {"thread_id": "t-rescue"}}

        class FakeSnap:
            def __init__(self, values):
                self.next = ("code",)
                self.values = values

        # 裁决 recovery.escalate=True (裁决路径已发求援卡) → 去重: 普通确认
        runner.app.get_state = lambda cfg: FakeSnap({
            "escalated_signature": "sig-1",
            "manager_verdicts": [{"node": "code", "decision": "redo", "recovery": {
                "escalate": True, "attempts": 3, "reason": "编译失败",
                "strategy": {"strategy": "escalate"},
            }}],
        })
        events = [ev async for ev in runner._announce_paused_worker(config, False)]
        assert not [e for e in events if e["event_type"] == "manager_message"]
        confirms = [e for e in events if e["event_type"] == "human_confirm_required"]
        assert confirms and "未通过" in confirms[0]["data"]["message"]

        # 熔断标记存在但裁决无 escalate (外部标记) → 这里发射求援卡
        runner.app.get_state = lambda cfg: FakeSnap({
            "escalated_signature": "sig-2",
            "manager_verdicts": [{"node": "code", "decision": "redo", "recovery": {
                "escalate": False, "attempts": 2, "reason": "编译失败",
                "strategy": {"strategy": "redispatch"},
            }}],
        })
        events2 = [ev async for ev in runner._announce_paused_worker(config, False)]
        cards = [e["data"] for e in events2 if e["event_type"] == "manager_message"]
        assert cards and cards[0]["card"] == "diagnosis_card"
        assert cards[0]["options"] == list(RESCUE_OPTIONS)
        assert "继续自主" in cards[0]["data"]["suggestion"]

    @pytest.mark.asyncio
    async def test_e2e_loop_break_carries_classification(self):
        """9.4: LoopControl 熔断 → loop_break 携带失败分类 (no_convergence) +
        恢复事件 + 红线标记 (resume 时「继续自主」消费)."""
        from unittest.mock import patch

        from app.services.generation.graph import GraphRunner

        runner = GraphRunner()
        state = _state(
            analysis_result=PRD_OK,
            design_result=DESIGN_OK,
            code_result=json.dumps({"App.vue": "<template>x</template>"}),
            generated_files={"App.vue": "<template>x</template>"},
        )
        config = {"configurable": {"thread_id": "gen-rec-e2e"}}
        [ev async for ev in runner.run(state, "gen-rec-e2e")]
        runner.app.update_state(config, {
            "e2e_user_confirmed": True,
            "e2e_test_cases": [{"id": "tc-1", "requirement_id": "R-01", "scenario": "x", "steps": []}],
            "rollback_count": {"code": 3},
        })
        results = [{"case_id": "tc-1", "passed": False, "status": "failed", "error": "boom"}]
        events = [ev async for ev in runner.resume_after_e2e("gen-rec-e2e", results)]
        break_ev = next(e for e in events if e["event_type"] == "loop_break")
        assert break_ev["data"]["classification"] == "no_convergence"
        assert break_ev["data"]["strategy"] == "escalate"
        snap = runner.app.get_state(config)
        assert snap.values["needs_manual_review"] is True
        assert snap.values["escalated_signature"]
        assert len(snap.values["recovery_events"]) == 1
        assert snap.values["recovery_events"][0]["result"] == "escalated"
        # 「继续自主」resume → 计数重置 (该问题签名清除; gate 重新把关可能
        # 产生新问题的新计数, 但熔断签名不再残留)。
        sig = break_ev["data"]["signature"]
        with patch("app.services.generation.nodes._llm_generate") as _mock:  # noqa: F841
            [ev async for ev in runner.resume("gen-rec-e2e")]
        snap2 = runner.app.get_state(config)
        assert not snap2.values.get("escalated_signature")
        assert sig not in (snap2.values.get("problem_attempts") or {})


# ---------------------------------------------------------------------------
# 9.5 持久化 + 历史策略复用
# ---------------------------------------------------------------------------


class TestPersistence:
    @pytest.mark.asyncio
    async def test_classification_writes_problems_jsonl(self):
        from app.services.generation.memory import project_root_for, read_problems

        state = _state()
        await run_recovery(state, node="code", decision="redo", reason="编译未通过", evidence=COMPILE_EVIDENCE)
        records = read_problems(project_root_for(state))
        assert records and records[-1]["category"] == "compile"
        assert records[-1]["result"] == "pending"
        assert "重派" in records[-1]["fix"]

    @pytest.mark.asyncio
    async def test_resolve_outcomes_and_success_counting(self):
        """gate 通过 → 未决恢复事件闭环: 最新 → resolved, 其余 → stale,
        fix_strategies 成功计数 (与分类时同一策略键)."""
        from app.services.generation.memory_db import get_memory_db

        db = get_memory_db()
        # 分类时 _persist_recovery 已记过尝试 (同键), resolve 只补成功计数。
        db.record_fix_strategy_success("compile", "重派（带反馈） → code")
        db.record_fix_strategy_success("compile", "拆分（并行子任务） → code")
        state = _state(recovery_events=[
            {"node": "code", "category": "compile", "reason": "旧问题", "strategy": "redispatch",
             "target": "code", "output_signature": "old", "result": "pending"},
            {"node": "code", "category": "compile", "reason": "当前问题", "strategy": "split",
             "target": "code", "output_signature": "cur", "result": "pending"},
        ])
        resolve_recovery_outcomes(state, "code")
        events = state["recovery_events"]
        assert events[0]["result"] == "stale"
        assert events[1]["result"] == "resolved"
        rows = {r["strategy"]: r for r in db.get_fix_strategies()}
        # 只有闭环为 resolved 的策略计成功 (stale 不计数)。
        assert rows["拆分（并行子任务） → code"]["success_count"] == 1
        assert rows["重派（带反馈） → code"]["success_count"] == 0

    @pytest.mark.asyncio
    async def test_gate_pass_resolves_pending_recovery(self):
        from app.services.generation.graph import GraphRunner

        runner = GraphRunner()
        state = _code_state(compile_errors=list(COMPILE_EVIDENCE["compile_errors"]))
        await runner._gate_manual_stage(state, "code")
        assert state["recovery_events"][-1]["result"] == "pending"
        # 同一 runner 的状态续接: 修复后通过 → resolved
        state2 = _state(
            code_result=json.dumps({"App.vue": "<template>ok</template>"}),
            generated_files={"App.vue": "<template>ok</template>"},
            compile_errors=None,
            recovery_events=list(state["recovery_events"]),
            problem_attempts=dict(state["problem_attempts"]),
            manager_verdicts=list(state["manager_verdicts"]),
            rollback_count=dict(state["rollback_count"]),
            rollback_records=list(state["rollback_records"]),
        )
        await runner._gate_manual_stage(state2, "code")
        assert state2["recovery_events"][-1]["result"] == "resolved"

    @pytest.mark.asyncio
    async def test_retrieval_suggested_fix(self):
        """9.5 场景: 增量开发中出现同类失败 → 检索历史策略作为分类建议."""
        from app.services.generation.memory_db import get_memory_db

        db = get_memory_db()
        db.record_fix_strategy_success("compile", "拆分修复")
        db.record_fix_strategy_result("compile", "拆分修复", success=True)
        state = _state()
        cls = await classify_failure(state, node="code", reason="编译未通过", evidence=COMPILE_EVIDENCE)
        assert "拆分修复" in cls["suggested_fix"]
        assert retrieve_fix_strategies(state, category="compile")[0]["strategy"] == "拆分修复"
        assert retrieve_fix_strategies(state, category="drift") == []

    def test_debugger_prompt_has_history(self):
        from app.services.generation.debugger import build_diagnosis_prompt
        from app.services.generation.memory_db import get_memory_db

        get_memory_db().record_fix_strategy_success("compile", "拆分修复")
        prompt = build_diagnosis_prompt(_state(), COMPILE_EVIDENCE)
        assert "历史修复策略" in prompt
        assert "拆分修复" in prompt

    def test_history_block_empty_without_history(self):
        assert history_strategies_block(_state()) == ""


# ---------------------------------------------------------------------------
# 端到端: 红线 → 求援 → 「继续自主」 → 重置 → 闭环
# ---------------------------------------------------------------------------


class TestEndToEndRedLine:
    @pytest.mark.asyncio
    async def test_design_red_line_continue_autonomous_resets_and_passes(self):
        """设计把关失败 3 次 → 求援卡; 「继续自主」resume → 计数重置 →
        阶段 2 重跑 → 通过, 未决恢复事件闭环为 resolved."""
        from unittest.mock import patch

        from app.services.generation.graph import GraphRunner

        DESIGN_MD = "# 设计方案\n组件树结构\n数据流设计\n样式方案\n文件拆分方案\n关键实现要点"
        L2_FAIL = json.dumps({"passed": False, "missing": [
            {"feature": "订单管理", "evidence": "PRD 声明，Spec 无对应"},
        ]}, ensure_ascii=False)
        L2_PASS = '{"passed": true, "missing": []}'
        CLASSIFY = ('{"category": "drift", "reason": "Spec 遗漏功能点", '
                    '"scope_change": {"required": false, "note": ""}}')
        # 3 次失败 (spec/L2/分类) × 3 + 第 4 次通过 (spec/L2)
        SEQUENCE = [json.dumps(SPEC_OK, ensure_ascii=False), L2_FAIL, CLASSIFY] * 3 + \
                   [json.dumps(SPEC_OK, ensure_ascii=False), L2_PASS]

        json_calls = []

        async def fake(system_prompt, user_prompt):
            idx = len(json_calls)
            json_calls.append((system_prompt, user_prompt))
            return SEQUENCE[idx]

        md_calls = []

        async def fake_md(system_prompt, user_content, **kwargs):
            md_calls.append(user_content)
            return DESIGN_MD

        def _cards(events):
            return [e["data"] for e in events if e["event_type"] == "manager_message"]

        def _rescue(cards):
            return [c for c in cards if c["card"] == "diagnosis_card" and c.get("options")]

        runner = GraphRunner(llm_fn=fake)
        with patch("app.services.generation.nodes._llm_generate", new=fake_md):
            state = _state(analysis_result=PRD_OK)
            # run #1 (自主第 1 轮): 普通诊断卡, 无求援。
            events = [ev async for ev in runner.run(state, "gen-redline")]
            assert not _rescue(_cards(events))
            # 用户确认 → resume (手动阶段 resume = 阶段 2 重跑, run #2, 第 2 轮)。
            events2 = [ev async for ev in runner.resume("gen-redline")]
            assert not _rescue(_cards(events2))
            # 用户确认 → resume (run #3, 第 3 轮) → 红线求援卡 (继续自主/转人工)。
            events3 = [ev async for ev in runner.resume("gen-redline")]
            rescue = _rescue(_cards(events3))
            # 用户选择「继续自主」→ resume: 计数重置 → run #4 阶段 2 重跑通过;
            # 消费到 design pass 裁决即停 (不再进入 code 阶段)。
            async for ev in runner.resume("gen-redline"):
                if ev.get("event_type") == "manager_verdict" \
                        and ev.get("data", {}).get("node") == "design":
                    break

        assert rescue[0]["options"] == list(RESCUE_OPTIONS)
        # 第 4 次 (求援后 resume): 计数已重置 → 重跑通过
        assert state["problem_attempts"] == {}
        assert state["manager_verdicts"][-1]["node"] == "design"
        assert state["manager_verdicts"][-1]["decision"] == "pass"
        assert state["design_result"] == DESIGN_MD
        # 未决恢复事件: 前 2 次 pending → 最近 resolved, 前次 stale;
        # 第 3 次红线事件在分类时即记 escalated (结果不随后续闭环改写)。
        results = [e["result"] for e in state["recovery_events"]]
        assert results.count("resolved") == 1
        assert results.count("stale") == 1
        assert "escalated" in results
        # 重派反馈进入第 4 次生成的 prompt (9.2 带反馈)
        assert any("失败分类" in m for m in md_calls)


# ---------------------------------------------------------------------------
# Review fixes: I3 (analysis guard), I4 (split wiring), I6 (single pattern row),
# M5 (scope note into code prompt), C1 (resume-same-runner continuity)
# ---------------------------------------------------------------------------


class TestReviewFixes:
    @pytest.mark.asyncio
    async def test_i6_single_failure_pattern_row(self):
        """I6: 一次分类只落一条 failure_pattern — 稳定键 (category:签名前缀),
        同问题重复失败在同一行累积计数, 不再产生近唯一键的第二行。"""
        from app.services.generation.memory_db import get_memory_db

        state = _state()
        await run_recovery(state, node="code", decision="redo", reason="编译未通过", evidence=COMPILE_EVIDENCE)
        await run_recovery(state, node="code", decision="redo", reason="编译未通过", evidence=COMPILE_EVIDENCE)
        db = get_memory_db()
        patterns = [p for p in db.get_failure_patterns(state["user_id"])
                    if p["pattern_key"].startswith("compile:")]
        assert len(patterns) == 1
        assert patterns[0]["count"] == 2  # 同问题重复失败 → 同一行累积

    @pytest.mark.asyncio
    async def test_i4_split_instruction_drives_debugger(self):
        """I4: split 策略 → Debugger 诊断 prompt 携带"拆分修复范围"指令块。"""
        from app.services.generation.debugger import build_diagnosis_prompt

        state = _state(recovery_last={
            "node": "code", "strategy": {"strategy": "split", "target": "code"},
            "reason": "重派一轮未通过，问题集中在具体文件 → 拆分修复范围（并行子任务）",
        })
        assert "拆分修复范围" in split_instruction_block(state)
        prompt = build_diagnosis_prompt(state, COMPILE_EVIDENCE)
        assert "恢复策略：拆分修复范围" in prompt
        # 非 split (或非 code 节点) → 空块
        assert split_instruction_block(_state()) == ""

    @pytest.mark.asyncio
    async def test_m5_scope_note_reaches_code_rerun_prompt(self):
        """M5: 已确认的范围变更进入 code 重跑 prompt (failure_details 通道)。"""
        from app.services.generation.manager import manager_gate

        out = await manager_gate(_code_state(
            compile_errors=list(COMPILE_EVIDENCE["compile_errors"]),
            scope_change_approved="删减订单模块",
        ))
        fd = out["failure_details"]
        assert fd["source"] == "code"
        assert "删减订单模块" in fd["instruction"]

    @pytest.mark.asyncio
    async def test_i3_analysis_redo_clears_and_feeds_back(self):
        """I3: 分析把关失败 → 清空 PRD 产物, resume 后阶段 1 带反馈重跑 —
        失败的 PRD 不再静默进入方案设计。"""
        from unittest.mock import patch

        from app.services.generation.graph import GraphRunner

        PRD_BAD = "# 需求规格文档\n\n## 1. 功能概述\n这是一个不完整的需求文档。"
        md_calls = []

        async def fake_md(system_prompt, user_content, **kwargs):
            md_calls.append(user_content)
            return PRD_BAD if len(md_calls) == 1 else PRD_OK

        runner = GraphRunner()
        state = _state()
        with patch("app.services.generation.nodes._llm_generate", new=fake_md):
            events = [ev async for ev in runner.run(state, "gen-i3-analysis")]
            # redo → 产物清空, 流水线停住 (不进入设计)
            assert state["manager_verdicts"][-1]["node"] == "analysis"
            assert state["manager_verdicts"][-1]["decision"] == "redo"
            assert state["analysis_result"] is None
            assert not [e for e in events if e["stage"] == "design"]
            # 用户确认 → resume (生产 confirmStage 对失败阶段走 mode=resume)
            events2 = [ev async for ev in runner.resume("gen-i3-analysis")]
            assert state["manager_verdicts"][-1]["decision"] == "pass"
            assert state["analysis_result"] == PRD_OK
        # 重派反馈进入重生成 prompt (I3 镜像 design_gate_feedback)
        assert "Manager 把关反馈" in md_calls[1]
        assert "PRD 缺少关键章节" in md_calls[1]

    @pytest.mark.asyncio
    async def test_i3_phase2_guard_blocks_failed_analysis(self):
        """I3 defense-in-depth: 崩溃恢复出"失败的 PRD + redo 裁决" → 阶段 2 入口
        清空并停等, 不进入设计。"""
        from app.services.generation.graph import GraphRunner

        runner = GraphRunner()
        state = _state(
            analysis_result=PRD_OK,
            manager_verdicts=[
                {"node": "analysis", "decision": "redo",
                 "reason": "PRD 缺少关键章节：功能模块", "signature": "s1", "at": "t"},
            ],
        )
        events = [ev async for ev in runner.run(state, "gen-i3-guard")]
        assert state["analysis_result"] is None
        errors = [e for e in events if e["event_type"] == "error"]
        assert errors and "需求规格未通过" in errors[0]["data"]["reason"]

    @pytest.mark.asyncio
    async def test_c1_resume_same_runner_preserves_recovery_state(self):
        """C1: 把关失败后确认走 mode=resume 同一 runner — problem_attempts /
        rollback_count / 裁决在 run→resume 循环间延续 (生产 confirmStage 对
        失败阶段改为 resume 的等价后端路径)。"""
        from unittest.mock import patch

        from app.services.generation.graph import GraphRunner

        DESIGN_MD = "# 设计方案\n组件树结构\n数据流设计\n样式方案\n文件拆分方案\n关键实现要点"
        json_calls = []

        async def fake(system_prompt, user_prompt):
            json_calls.append((system_prompt, user_prompt))
            if len(json_calls) == 1:
                return json.dumps(SPEC_OK, ensure_ascii=False)
            if len(json_calls) == 2:
                return json.dumps({"passed": False, "missing": [
                    {"feature": "订单管理", "evidence": "PRD 声明"},
                ]}, ensure_ascii=False)
            if len(json_calls) == 3:
                return '{"category": "drift", "reason": "Spec 遗漏订单管理", "scope_change": {"required": false, "note": ""}}'
            if len(json_calls) == 4:
                return json.dumps(SPEC_OK, ensure_ascii=False)
            return '{"passed": true, "missing": []}'

        async def fake_md(system_prompt, user_content, **kwargs):
            return DESIGN_MD

        runner = GraphRunner(llm_fn=fake)
        with patch("app.services.generation.nodes._llm_generate", new=fake_md):
            state = _state(analysis_result=PRD_OK)
            events = [ev async for ev in runner.run(state, "gen-c1-resume")]
            assert state["manager_verdicts"][-1]["decision"] == "redo"
            assert list(state["problem_attempts"].values()) == [1]
            assert state["rollback_count"]["design"] == 1
            # 生产 confirmStage 等价: 失败阶段 → mode=resume 同一 runner
            events2 = [ev async for ev in runner.resume("gen-c1-resume")]
            assert state["manager_verdicts"][-1]["decision"] == "pass"
            assert state["design_result"] == DESIGN_MD
        # 计数跨 resume 延续 (不再累积新失败)
        assert list(state["problem_attempts"].values()) == [1]
        assert state["rollback_count"]["design"] == 1
