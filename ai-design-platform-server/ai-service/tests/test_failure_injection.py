"""Task 11.3 — 失败注入演练 (恢复阶梯与红线).

(a) 编译错误注入 → Verifier L1 失败 → Debugger 修复轮 → 重新验证通过;
(b) 同证据重复失败 → Debugger 无进展熔断 → gate 恢复阶梯 (重派→拆分) →
    红线求援卡 (继续自主/转人工) → 继续自主重置 → 重跑通过;
(c) 设计漂移 (Spec 漏 PRD 功能点) → L2 重做 → 带反馈重新生成 → 通过;
(d) 代码节点中断 → 由 11.5 演练覆盖 (test_crash_recovery_drill.py)。

编译失败通过 FailingCompileRegistry 注入 (前端 bundler 上报语义的测试替身),
与真实 phase-3 流水线 (executor → compile → verifier → debugger → gate) 全链路。
problems.jsonl + recovery 事件持久化在每个用例断言。
"""

import asyncio
import json

import pytest

from app.services.generation import nodes
from app.services.generation.graph import GraphRunner

from .drill_helpers import (
    CLASSIFY_DRIFT,
    DAG_ONE,
    DESIGN_MD,
    DIAGNOSIS_FIX,
    FailingCompileRegistry,
    FILE_APP,
    FILE_APP_BAD,
    L2_FAIL_ORDER,
    L2_PASS,
    MARK_DESIGN_MD,
    MARK_L2,
    MARK_PLANNER,
    MARK_PRD,
    MARK_SPEC,
    PRD_OK,
    SPEC_L,
    SPEC_SM,
    ScriptedFlowProvider,
    base_state,
    cards_of,
    done_turn,
    events_of,
    project_root_of,
    token_turn,
)
from .test_recovery import RESCUE_OPTIONS


def _l_state(**overrides) -> dict:
    """L 档 state: analysis/design 已过, 代码阶段待跑 (SPEC_L → 角色含
    debugger/tester, 恢复阶梯可走)。"""
    return base_state(
        analysis_result=PRD_OK,
        design_result=DESIGN_MD,
        design_doc=DESIGN_MD,
        architecture_spec=dict(SPEC_L),
        **overrides,
    )


# ── (a) 编译错误 → L1 失败 → Debugger 修复 → 通过 ──


@pytest.mark.asyncio
async def test_compile_error_verifier_fail_debugger_fix_pass(monkeypatch):
    """编译错误注入 (前端 bundler 上报语义) → verifier L1 失败 → Debugger
    证据链修复 → 修复后重新验证通过 → gate pass。"""
    monkeypatch.setattr(
        "app.services.generation.tools.registry.ToolRegistry", FailingCompileRegistry
    )

    provider = ScriptedFlowProvider()
    provider.script(MARK_PLANNER, token_turn(DAG_ONE))
    provider.files = {"src/App.vue": FILE_APP_BAD}
    provider.enable_executor_heuristic()
    # fake_diagnose 双重职责: 诊断 (翻转文件为修复版 — 修复轮重跑写 GOOD) +
    # Tester 的 LLM 调用 (L 档, 输出空测试 → 诚实 l4_pending, 无 node 依赖)。
    diag_calls = []

    async def fake_llm(system_prompt, user_prompt):
        diag_calls.append(system_prompt[:60])
        if "验收先行" in system_prompt:
            return '{"tests": []}'
        provider.files["src/App.vue"] = FILE_APP  # 模拟修复指令被执行的产物
        return DIAGNOSIS_FIX

    old = nodes._provider
    nodes._provider = provider
    try:
        state = _l_state(generation_id="gen-inj-a")
        runner = GraphRunner(llm_fn=fake_llm)
        events = []
        async for ev in runner.run(state, "gen-inj-a"):
            events.append(ev)
            if ev.get("event_type") == "manager_verdict" and ev.get("data", {}).get("node") == "code":
                break
    finally:
        nodes._provider = old

    # 编译先失败后通过 (修复轮重编译)
    compiles = events_of(events, "compile_status")
    assert compiles[0]["data"]["ok"] is False
    assert compiles[0]["data"]["errors"][0]["text"].startswith("Unexpected token")
    assert compiles[-1]["data"]["ok"] is True
    # Verifier: L1 失败 → 修复后通过 (L 档 Tester 空产物 → l4_pending 不判失败)
    verifier_events = events_of(events, "verifier_result")
    assert verifier_events[0]["data"]["passed"] is False
    assert verifier_events[0]["data"]["l1_ok"] is False
    assert verifier_events[-1]["data"]["passed"] is True
    # Debugger: 证据链修复 1 轮 (诊断 → 重派 → 重编译)
    assert len(events_of(events, "debugger_diagnosis")) == 1
    diagnosis = events_of(events, "debugger_diagnosis")[0]
    assert diagnosis["data"]["affected_files"] == ["src/App.vue"]
    # 修复指令进入重派 executor 的 prompt (5.5)
    assert len(diag_calls) >= 1
    # 最终 gate pass
    verdicts = events_of(events, "manager_verdict")
    assert verdicts[-1]["data"]["decision"] == "pass"
    assert state["verifier_result"]["passed"] is True
    # 修复闭环产物: 磁盘上是修复后的文件
    from app.services.generation.memory import scan_generated_files

    files = scan_generated_files(project_root_of(state))
    assert "BAD" not in files["src/App.vue"]


# ── (b) 同证据重复失败 → 无进展 → 红线求援 → 继续自主 → 通过 ──


@pytest.mark.asyncio
async def test_repeated_failure_red_line_rescue_then_reset_pass(monkeypatch):
    """同证据持续失败: Debugger 修复轮证据不变 → 无进展熔断 → gate 分类
    no_convergence → 红线求援卡 (继续自主/转人工), 不再自主派发 →
    「继续自主」重置 → 修复后重跑通过。problems.jsonl + recovery 事件留痕。
    (尝试计数阶梯 重派→拆分→红线 由 test_manual_gate_red_line_emits_rescue_card /
    test_gate_red_line_escalates_after_three 覆盖; 本用例注入真实 phase 3
    无进展路径。)"""
    from app.services.generation.memory import read_problems
    from app.services.generation.recovery import consume_escalation_reset

    monkeypatch.setattr(
        "app.services.generation.tools.registry.ToolRegistry", FailingCompileRegistry
    )

    async def fake_llm(system_prompt, user_prompt):
        # 诊断永不修复 (同 BAD 内容) → 证据不变 → 无进展; Tester 空产物。
        if "验收先行" in system_prompt:
            return '{"tests": []}'
        return DIAGNOSIS_FIX

    provider = ScriptedFlowProvider()
    provider.script(MARK_PLANNER, token_turn(DAG_ONE))
    provider.files = {"src/App.vue": FILE_APP_BAD}
    provider.enable_executor_heuristic()

    old = nodes._provider
    nodes._provider = provider
    try:
        state = _l_state(generation_id="gen-inj-b")
        runner = GraphRunner(llm_fn=fake_llm)

        # 第 1 次自主尝试: 真实 phase 3 → Debugger 无进展 → gate 红线求援
        events = []
        async for ev in runner.run(state, "gen-inj-b"):
            events.append(ev)
            if ev.get("event_type") == "human_confirm_required":
                break  # 裁决与求援卡已随 gate 事件流出
        stopped = events_of(events, "debugger_stopped")
        assert stopped and "无进展" in stopped[0]["data"]["reason"]
        assert len(events_of(events, "debugger_diagnosis")) == 1  # 只诊断一次
        first_verdict = events_of(events, "manager_verdict")[-1]
        assert first_verdict["data"]["decision"] == "redo"
        # 无进展 → no_convergence 分类 → 红线: 求援卡 (继续自主/转人工)
        rec = state["manager_verdicts"][-1]["recovery"]
        assert rec["category"] == "no_convergence"
        assert rec["escalate"] is True
        rescue = [c for c in cards_of(events) if c["card"] == "diagnosis_card" and c.get("options")]
        assert rescue and rescue[0]["options"] == list(RESCUE_OPTIONS)
        assert state["needs_manual_review"] is True
        assert state["escalated_signature"]
        assert state["recovery_events"][-1]["result"] == "escalated"

        # problems.jsonl 留痕 (9.5): verifier 失败 + no_convergence 求援
        problems = read_problems(project_root_of(state))
        assert any(p["category"] == "verifier_failure" for p in problems)
        assert any(p["category"] == "no_convergence" and p["result"] == "escalated"
                   for p in problems)

        # 「继续自主」= consume_escalation_reset (resume 路径调用点)
        assert consume_escalation_reset(state) is True
        assert state["problem_attempts"] == {}
        assert not state.get("escalated_signature")

        # 修复后重跑: 翻转文件为 GOOD → phase 3 重生成 → 通过 (不再求援)
        provider.files["src/App.vue"] = FILE_APP
        state["generated_files"] = {}
        state["code_result"] = None
        state["compile_errors"] = None
        state["verifier_result"] = None
        events4 = []
        async for ev in runner.run(state, "gen-inj-b"):
            events4.append(ev)
            if ev.get("event_type") == "manager_verdict" and ev.get("data", {}).get("node") == "code":
                break
        final = events_of(events4, "manager_verdict")[-1]
        assert final["data"]["decision"] == "pass"
        assert state["verifier_result"]["passed"] is True
        assert not [c for c in cards_of(events4) if c.get("options")]
    finally:
        nodes._provider = old


# ── (c) 设计漂移: Spec 漏 PRD 功能点 → L2 重做 → 带反馈重新生成 → 通过 ──


@pytest.mark.asyncio
async def test_drift_design_l2_redo_regenerates_with_feedback():
    """PRD 声明订单管理, Spec 无对应页面 → L2 把关不通过 (缺失清单) →
    恢复阶梯重派 → 阶段 2 带缺失清单反馈重新生成 → L2 通过。"""
    SPEC_FIXED = {
        **SPEC_SM,
        "pages": [
            {"id": "p-01", "name": "首页", "interactions": [], "data": []},
            {"id": "p-02", "name": "订单列表", "interactions": [], "data": []},
        ],
    }
    spec_calls: list[str] = []
    l2_calls: list[str] = []
    classify_calls: list[str] = []

    async def fake_llm(system_prompt, user_prompt):
        if "机器可读的架构 Spec" in system_prompt:
            spec_calls.append(user_prompt)
            if len(spec_calls) == 1:
                return json.dumps(SPEC_SM, ensure_ascii=False)
            return json.dumps(SPEC_FIXED, ensure_ascii=False)
        if "核对架构 Spec 对 PRD 功能点的覆盖情况" in system_prompt:
            l2_calls.append(user_prompt)
            return L2_FAIL_ORDER if len(l2_calls) == 1 else L2_PASS
        if "失败分类器" in system_prompt:
            classify_calls.append(user_prompt)
            return CLASSIFY_DRIFT
        raise AssertionError(f"unexpected llm_fn call: {system_prompt[:60]}")

    provider = ScriptedFlowProvider()
    provider.script(MARK_DESIGN_MD, token_turn(DESIGN_MD), token_turn(DESIGN_MD))  # 重做轮

    old = nodes._provider
    nodes._provider = provider
    try:
        state = base_state(
            generation_id="gen-inj-c",
            analysis_result=PRD_OK,
        )
        runner = GraphRunner(llm_fn=fake_llm)
        events = []
        async for ev in runner.run(state, "gen-inj-c"):
            events.append(ev)
        # L2 不通过: 缺失清单进裁决与诊断卡 (4.4)
        verdicts = events_of(events, "manager_verdict")
        assert verdicts[-1]["data"]["node"] == "design"
        assert verdicts[-1]["data"]["decision"] == "redo"
        assert any("订单管理" in m.get("feature", "") for m in verdicts[-1]["data"]["missing"])
        diagnosis = cards_of(events, "diagnosis_card")
        assert diagnosis and "订单管理" in diagnosis[-1]["content"]
        # 重做语义: 双产物清空, 不进入实现阶段 (把关先行于确认, 1.8)
        assert state["design_result"] is None
        assert state["architecture_spec"] is None
        assert not [e for e in events if e["stage"] == "code"]
        # 恢复阶梯: 分类 drift → 重派 (带反馈)
        rec = state["manager_verdicts"][-1]["recovery"]
        assert rec["category"] == "drift"
        assert rec["strategy"]["strategy"] == "redispatch"
        assert not rec["escalate"]

        # 用户确认 → resume → 阶段 2 重跑: 重派反馈 (缺失清单) 进入生成 prompt
        events2 = []
        async for ev in runner.resume(state["generation_id"]):
            events2.append(ev)
            if ev.get("event_type") == "manager_verdict" and ev.get("data", {}).get("node") == "design":
                break
        verdicts2 = events_of(events2, "manager_verdict")
        assert verdicts2[-1]["data"]["decision"] == "pass"
        assert state["design_result"] == DESIGN_MD
        assert state["architecture_spec"]["pages"][1]["name"] == "订单列表"
        assert "Manager 把关反馈" in spec_calls[1]
        assert "订单管理" in spec_calls[1]
        # 重派不重建全流程 (7.3): 阶段 1 未重跑
        assert not [e for e in events2 if e["event_type"] == "prd_generate_start"]
    finally:
        nodes._provider = old


def test_interrupt_mid_code_maps_to_crash_recovery_drill():
    """(d) 代码节点中断 (进程终止/取消) 的恢复语义由 11.5 演练覆盖 —
    test_crash_recovery_drill.py::test_crash_mid_code_resume_completes_pipeline
    (加载 .ai-memory → 已完成阶段跳过 → 中断的代码阶段续跑)。"""
    # 显式引用避免死引用: 该测试存在性由 test_spec_traceability 守卫。
    import importlib

    try:
        mod = importlib.import_module("tests.test_crash_recovery_drill")
    except ImportError:
        mod = importlib.import_module("test_crash_recovery_drill")
    assert hasattr(mod, "test_crash_mid_code_resume_completes_pipeline")
