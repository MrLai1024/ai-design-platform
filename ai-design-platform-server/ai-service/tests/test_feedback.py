"""Tests for task group 10: 反馈链路迁移 (10.1 反馈 → Manager 恢复决策).

Covers: 反馈分类 (确定性 + LLM seam + fail-safe), 处置挂起 (遗漏/纠偏 →
重派指令; 范围变更 → pending_scope_change; 拒绝标记跳过), run/resume 入口
消费 (重派指令注入 + 处置卡 + checkpoint 同步), servicer ReportUserFeedback
(200 / NOT_FOUND), 旧 planner 自我审查路径移除 (code_feedback 不再进 prompt)。
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.generation.recovery import SCOPE_OPTIONS

from .test_recovery import DESIGN_OK, PRD_OK, SPEC_OK, _state


def _code_state(**overrides) -> dict:
    return _state(
        analysis_result=PRD_OK,
        design_result=DESIGN_OK,
        design_doc=DESIGN_OK,
        architecture_spec=dict(SPEC_OK),
        code_result=json.dumps({"App.vue": "<template>x</template>"}, ensure_ascii=False),
        generated_files={"App.vue": "<template>x</template>"},
        **overrides,
    )


# ---------------------------------------------------------------------------
# 10.1 反馈分类: 确定性短语优先 (zero-LLM)
# ---------------------------------------------------------------------------


class TestClassifyDeterministic:
    @pytest.mark.asyncio
    async def test_omission_marker(self):
        from app.services.generation.feedback import classify_user_feedback

        cls = await classify_user_feedback("缺少登录组件")
        assert cls["category"] == "omission"
        assert cls["confidence"] == "high"  # 确定性短语命中 (review fix)

    @pytest.mark.asyncio
    async def test_correction_marker(self):
        from app.services.generation.feedback import classify_user_feedback

        cls = await classify_user_feedback("按钮样式需要修改")
        assert cls["category"] == "correction"
        assert cls["confidence"] == "high"

    @pytest.mark.asyncio
    async def test_scope_change_marker(self):
        from app.services.generation.feedback import classify_user_feedback

        cls = await classify_user_feedback("新增一个订单导出功能")
        assert cls["category"] == "scope_change"
        assert cls["confidence"] == "high"

    @pytest.mark.asyncio
    async def test_bu_bu_chong_not_misclassified_as_correction(self):
        """review fix: 「补充登录功能」不得因单字「补」误命中 correction —
        无唯一短语命中 → LLM (模糊路径), 绝不确定性误判。"""
        from app.services.generation.feedback import classify_user_feedback

        async def fake(system_prompt, user_prompt):
            return '{"category": "omission", "reason": "需求已声明但未生成", "scope_note": ""}'

        cls = await classify_user_feedback("请补充登录功能", llm_fn=fake)
        assert cls["category"] == "omission"
        assert cls["confidence"] == "medium"

    @pytest.mark.asyncio
    async def test_ambiguous_uses_llm_seam(self):
        """无唯一短语命中 → LLM 判断 (medium confidence)."""
        from app.services.generation.feedback import classify_user_feedback

        async def fake(system_prompt, user_prompt):
            return '{"category": "correction", "reason": "细节调整", "scope_note": ""}'

        cls = await classify_user_feedback("页面整体效果不太符合预期", llm_fn=fake)
        assert cls["category"] == "correction"
        assert cls["confidence"] == "medium"
        assert cls["reason"] == "细节调整"

    @pytest.mark.asyncio
    async def test_llm_failure_falls_back_to_heuristic(self):
        """LLM 不可用 → 短语启发式回退 (low confidence). 文本需无唯一短语命中
        (多类别命中 → 模糊 → LLM 路径被触发)."""
        from app.services.generation.feedback import classify_user_feedback

        async def fake(system_prompt, user_prompt):
            raise RuntimeError("llm down")

        cls = await classify_user_feedback("缺少分页但新增了图表", llm_fn=fake)
        assert cls["category"] == "omission"  # 启发式: omission 优先
        assert cls["confidence"] == "low"

    @pytest.mark.asyncio
    async def test_llm_invalid_category_falls_back(self):
        from app.services.generation.feedback import classify_user_feedback

        async def fake(system_prompt, user_prompt):
            return '{"category": "nonsense", "reason": "x"}'

        cls = await classify_user_feedback("这个页面整体效果一般", llm_fn=fake)
        assert cls["category"] == "correction"  # 启发式兜底
        assert cls["confidence"] == "low"


# ---------------------------------------------------------------------------
# 10.1 处置挂起 (RPC 路径): dispose_user_feedback
# ---------------------------------------------------------------------------


class TestDisposeUserFeedback:
    @pytest.mark.asyncio
    async def test_omission_pends_redispatch_and_records_problem(self):
        from app.services.generation.feedback import dispose_user_feedback
        from app.services.generation.graph import GraphRunner
        from app.services.generation.memory_db import get_memory_db

        runner = GraphRunner(llm_fn=lambda *a: "")
        disp = await dispose_user_feedback(runner, "gen-fb-1", "code", "缺少订单列表组件")
        assert disp["category"] == "omission"
        assert disp["result"] == "dispatched"
        assert "重派" in disp["action"]
        pending = runner._pending_feedback
        assert pending["feedback"] == "缺少订单列表组件"
        # 问题记录落库 (memory_db problem_records)
        rows = get_memory_db().list_problems("gen-fb-1")
        assert any(r["category"] == "user_feedback" and r["result"] == "dispatched" for r in rows)

    @pytest.mark.asyncio
    async def test_scope_change_pends_confirm(self):
        from app.services.generation.feedback import dispose_user_feedback
        from app.services.generation.graph import GraphRunner

        runner = GraphRunner(llm_fn=lambda *a: "")
        disp = await dispose_user_feedback(runner, "gen-fb-2", "code", "新增导出 Excel 功能")
        assert disp["category"] == "scope_change"
        assert disp["result"] == "awaiting_confirm"
        assert runner._pending_feedback["scope_note"] == ""

    @pytest.mark.asyncio
    async def test_scope_reject_marker_skips_disposal(self):
        from app.services.generation.feedback import dispose_user_feedback
        from app.services.generation.graph import GraphRunner

        runner = GraphRunner(llm_fn=lambda *a: "")
        disp = await dispose_user_feedback(runner, "gen-fb-3", "code", "重新生成")
        assert disp["category"] == "scope_reject"
        assert disp["result"] == "rejected"
        assert runner._pending_feedback is None

    @pytest.mark.asyncio
    async def test_empty_feedback_rejected(self):
        from app.services.generation.feedback import dispose_user_feedback
        from app.services.generation.graph import GraphRunner

        runner = GraphRunner(llm_fn=lambda *a: "")
        disp = await dispose_user_feedback(runner, "gen-fb-4", "code", "   ")
        assert disp["result"] == "rejected"
        assert runner._pending_feedback is None

    @pytest.mark.asyncio
    async def test_second_feedback_while_pending_is_busy_rejected(self):
        """review fix: 上一条反馈尚未消费 → busy 拒绝, 绝不覆盖挂起处置."""
        from app.services.generation.feedback import dispose_user_feedback
        from app.services.generation.graph import GraphRunner

        runner = GraphRunner(llm_fn=lambda *a: "")
        first = await dispose_user_feedback(runner, "gen-fb-5", "code", "缺少订单列表组件")
        assert first["result"] == "dispatched"
        second = await dispose_user_feedback(runner, "gen-fb-5", "code", "按钮样式需要修改")
        assert second["result"] == "busy"
        assert second["category"] == ""
        # 第一条挂起原样保留 (未被覆盖)
        assert runner._pending_feedback["feedback"] == "缺少订单列表组件"


# ---------------------------------------------------------------------------
# 10.1 消费点: run() / resume() 入口
# ---------------------------------------------------------------------------


class TestConsumeAtRunEntry:
    @pytest.mark.asyncio
    async def test_run_consumes_redispatch_and_emits_card(self):
        """run() 入口: 遗漏反馈 → 重派指令注入 + 产物清空 + 处置卡首帧."""
        from app.services.generation.graph import GraphRunner

        runner = GraphRunner(llm_fn=lambda *a: "")
        state = _code_state(generation_id="gen-run-fb")
        runner._pending_feedback = {
            "feedback": "缺少订单列表组件",
            "stage": "code",
            "category": "omission",
            "reason": "需求已声明但未生成",
            "confidence": "low",
            "scope_note": "",
            "action": "重派功能实现任务（携带反馈）",
            "result": "dispatched",
            "category_label": "遗漏",
        }
        gen = runner.run(state, "gen-run-fb")
        first = await anext(gen)
        # 处置卡是首帧 (manager_message feedback_card)
        assert first["event_type"] == "manager_message"
        assert first["data"]["card"] == "feedback_card"
        assert first["data"]["data"]["category"] == "omission"
        # 重派指令注入 (failure_details.instruction = U9 redo 通道)
        assert "缺少订单列表组件" in state["failure_details"]["instruction"]
        assert "用户反馈" in state["failure_details"]["instruction"]
        # 产物清空 → run 重跑 phase 3 (重派)
        assert state["code_result"] is None
        assert state["generated_files"] == {}
        await gen.aclose()

    @pytest.mark.asyncio
    async def test_run_consumes_scope_change_halts_with_confirm_card(self):
        """run() 入口: 范围变更 → 处置卡 + confirm_card, halt (不自行重派)."""
        from app.services.generation.graph import GraphRunner

        runner = GraphRunner(llm_fn=lambda *a: "")
        state = _code_state(generation_id="gen-run-scope")
        runner._pending_feedback = {
            "feedback": "新增导出 Excel 功能",
            "stage": "code",
            "category": "scope_change",
            "reason": "超出当前需求范围",
            "confidence": "low",
            "scope_note": "导出 Excel",
            "action": "范围变更待确认（confirm_card）",
            "result": "awaiting_confirm",
            "category_label": "范围变更",
        }
        events = [ev async for ev in runner.run(state, "gen-run-scope")]
        cards = [ev["data"] for ev in events if ev["event_type"] == "manager_message"]
        assert [c["card"] for c in cards] == ["feedback_card", "confirm_card"]
        confirm = cards[1]
        assert confirm["options"] == list(SCOPE_OPTIONS)
        assert confirm["scope_confirm"] is True
        assert "导出 Excel" in confirm["content"]
        # pending_scope_change 挂起 (用户确认前不批准)
        assert state["pending_scope_change"]["node"] == "code"
        assert "导出 Excel" in state["pending_scope_change"]["note"]
        assert not state.get("scope_change_approved")

    @pytest.mark.asyncio
    async def test_run_fallback_consumes_metadata_code_feedback(self):
        """兜底通道: state.code_feedback (runner 重建 / metadata 注入) 在
        消费点等价处置, 消费后清除防重复."""
        from app.services.generation.graph import GraphRunner

        runner = GraphRunner(llm_fn=lambda *a: "")
        state = _code_state(generation_id="gen-run-meta", code_feedback="列表缺少分页")
        gen = runner.run(state, "gen-run-meta")
        first = await anext(gen)
        assert first["data"]["card"] == "feedback_card"
        assert first["data"]["data"]["category"] == "omission"
        assert state["code_feedback"] == ""  # 消费即清
        assert "列表缺少分页" in state["failure_details"]["instruction"]
        await gen.aclose()

    @pytest.mark.asyncio
    async def test_run_ignores_scope_reject_marker(self):
        from app.services.generation.graph import GraphRunner

        runner = GraphRunner(llm_fn=lambda *a: "")
        state = _code_state(generation_id="gen-run-reject", code_feedback="重新生成")
        events = [ev async for ev in runner.run(state, "gen-run-reject")]
        assert not [e for e in events if e.get("data", {}).get("card") == "feedback_card"]

    @pytest.mark.asyncio
    async def test_double_consume_no_second_card(self):
        """review fix (回归): 反馈在 run 入口消费后 (pending 已清) → resume
        入口不得再次发射处置卡。"""
        from app.services.generation.graph import GraphRunner

        runner = GraphRunner(llm_fn=lambda *a: "")
        state = _code_state(generation_id="gen-double")
        runner._pending_feedback = {
            "feedback": "缺少订单列表组件",
            "stage": "code",
            "category": "omission",
            "reason": "需求已声明但未生成",
            "confidence": "high",
            "scope_note": "",
            "action": "重派功能实现任务（携带反馈）",
            "result": "dispatched",
            "category_label": "遗漏",
        }
        # 1) run 入口消费 → 首帧处置卡
        gen = runner.run(state, "gen-double")
        first = await anext(gen)
        assert first["data"]["card"] == "feedback_card"
        await gen.aclose()
        assert runner._pending_feedback is None
        # 2) resume 入口 (state.code_result 已被清 → 转 run 重跑) 不再有处置卡
        events = []
        gen2 = runner.resume("gen-double")
        for _ in range(6):
            try:
                events.append((await anext(gen2)).get("data", {}).get("card"))
            except (StopAsyncIteration, RuntimeError):
                # 重跑阶段无 LLM provider 会抛错 — 只关心首段事件无处置卡
                break
        await gen2.aclose()
        assert "feedback_card" not in events


class TestConsumeAtResumeEntry:
    @pytest.mark.asyncio
    async def test_resume_consumes_redispatch_without_checkpoint(self):
        """resume() 入口: 无 checkpoint (手动阶段暂停) → 清 self._state 产物,
        转 run() 重跑; 处置卡首帧."""
        from app.services.generation.graph import GraphRunner

        runner = GraphRunner(llm_fn=lambda *a: "")
        state = _code_state(generation_id="gen-res-fb")
        runner._state = state
        runner._pending_feedback = {
            "feedback": "按钮样式需要修改",
            "stage": "code",
            "category": "correction",
            "reason": "实现与需求不符",
            "confidence": "low",
            "scope_note": "",
            "action": "重派功能实现任务（携带反馈）",
            "result": "dispatched",
            "category_label": "纠偏",
        }
        gen = runner.resume("gen-res-fb")
        first = await anext(gen)
        assert first["event_type"] == "manager_message"
        assert first["data"]["card"] == "feedback_card"
        assert state["code_result"] is None
        assert "按钮样式需要修改" in state["failure_details"]["instruction"]
        await gen.aclose()

    @pytest.mark.asyncio
    async def test_resume_consumes_redispatch_with_checkpoint_sync(self):
        """resume() 入口 + 已有 checkpoint (LangGraph 已启动): 处置同步进
        checkpoint (code_result 清空), self._state 产物保留 (走 LangGraph 续跑)."""
        from app.services.generation.graph import GraphRunner

        runner = GraphRunner(llm_fn=lambda *a: "")
        state = _code_state(generation_id="gen-res-ckpt", e2e_passed=True)
        # 跑到 END, 建立 checkpoint (与 test_recovery scope 测试同模式)。
        [ev async for ev in runner.run(state, "gen-res-ckpt")]
        runner._pending_feedback = {
            "feedback": "缺少订单列表组件",
            "stage": "code",
            "category": "omission",
            "reason": "需求已声明但未生成",
            "confidence": "low",
            "scope_note": "",
            "action": "重派功能实现任务（携带反馈）",
            "result": "dispatched",
            "category_label": "遗漏",
        }
        config = {"configurable": {"thread_id": "gen-res-ckpt"}}
        gen = runner.resume("gen-res-ckpt")
        first = await anext(gen)
        assert first["data"]["card"] == "feedback_card"
        # checkpoint 已同步: code_result 清空 (code worker 重跑), failure_details 注入
        snap = runner.app.get_state(config)
        assert snap.values.get("code_result") is None
        assert "缺少订单列表组件" in (snap.values.get("failure_details") or {}).get("instruction", "")
        # self._state 产物保留 → resume 走 LangGraph 续跑
        assert state["code_result"] is not None
        await gen.aclose()

    @pytest.mark.asyncio
    async def test_resume_scope_change_halts_with_checkpoint(self):
        """review fix: checkpoint 变体范围变更 — 处置同步进 checkpoint
        (pending_scope_change), halt; 用户确认后 checkpoint 消费批准."""
        from app.services.generation.graph import GraphRunner

        runner = GraphRunner(llm_fn=lambda *a: "")
        state = _code_state(generation_id="gen-res-scope-ckpt", e2e_passed=True)
        [ev async for ev in runner.run(state, "gen-res-scope-ckpt")]
        runner._pending_feedback = {
            "feedback": "新增数据看板模块",
            "stage": "code",
            "category": "scope_change",
            "reason": "超出当前需求范围",
            "confidence": "high",
            "scope_note": "数据看板",
            "action": "范围变更待确认（confirm_card）",
            "result": "awaiting_confirm",
            "category_label": "范围变更",
        }
        config = {"configurable": {"thread_id": "gen-res-scope-ckpt"}}
        events = [ev async for ev in runner.resume("gen-res-scope-ckpt")]
        cards = [ev["data"] for ev in events if ev["event_type"] == "manager_message"]
        assert [c["card"] for c in cards] == ["feedback_card", "confirm_card"]
        # checkpoint 同步了 pending_scope_change (用户确认 resume 后消费批准)
        snap = runner.app.get_state(config)
        assert (snap.values.get("pending_scope_change") or {}).get("signature") == "user-feedback"

    @pytest.mark.asyncio
    async def test_resume_scope_change_halts(self):
        """resume() 入口: 范围变更 → 处置卡 + confirm_card 后立即停止."""
        from app.services.generation.graph import GraphRunner

        runner = GraphRunner(llm_fn=lambda *a: "")
        state = _code_state(generation_id="gen-res-scope")
        runner._state = state
        runner._pending_feedback = {
            "feedback": "新增数据看板模块",
            "stage": "code",
            "category": "scope_change",
            "reason": "超出当前需求范围",
            "confidence": "low",
            "scope_note": "数据看板",
            "action": "范围变更待确认（confirm_card）",
            "result": "awaiting_confirm",
            "category_label": "范围变更",
        }
        events = [ev async for ev in runner.resume("gen-res-scope")]
        cards = [ev["data"] for ev in events if ev["event_type"] == "manager_message"]
        assert [c["card"] for c in cards] == ["feedback_card", "confirm_card"]
        assert state["pending_scope_change"]["signature"] == "user-feedback"

    @pytest.mark.asyncio
    async def test_scope_confirm_then_rerun_carries_approved_scope(self):
        """无 checkpoint 范围变更全链路: 消费 (halt) → 用户确认 → resume →
        run() 重跑 — 批准范围进入重派指令 (failure_details)。"""
        from app.services.generation.graph import GraphRunner

        runner = GraphRunner(llm_fn=lambda *a: "")
        state = _code_state(generation_id="gen-scope-full")
        runner._state = state
        runner._pending_feedback = {
            "feedback": "新增数据看板模块",
            "stage": "code",
            "category": "scope_change",
            "reason": "超出当前需求范围",
            "confidence": "low",
            "scope_note": "数据看板",
            "action": "范围变更待确认（confirm_card）",
            "result": "awaiting_confirm",
            "category_label": "范围变更",
        }
        # 1) 消费: 处置卡 + confirm_card + halt; 产物清空 (无 checkpoint)。
        events = [ev async for ev in runner.resume("gen-scope-full")]
        assert [ev["data"]["card"] for ev in events if ev["event_type"] == "manager_message"] == \
            ["feedback_card", "confirm_card"]
        assert state["code_result"] is None
        # 2) 用户「确认」→ resume: 消费无反馈 → consume_scope_confirmation 批准
        #    → run() 重跑, 批准范围进入 failure_details 重派指令。
        runner._state = state
        gen = runner.resume("gen-scope-full")
        first = await anext(gen)
        assert first["event_type"] != "error"
        assert state["scope_change_approved"]  # consume_scope_confirmation 已批准
        assert "数据看板" in state["failure_details"]["instruction"]
        assert "用户已确认的范围变更" in state["failure_details"]["instruction"]
        await gen.aclose()

    @pytest.mark.asyncio
    async def test_approved_scope_enters_redo_instruction_on_rerun(self):
        """用户确认范围变更后 run() 重跑: approval → failure_details 指令
        (手动阶段 gate 无注入点, run 入口消费)."""
        from app.services.generation.graph import GraphRunner

        runner = GraphRunner(llm_fn=lambda *a: "")
        state = _code_state(
            generation_id="gen-approve",
            pending_scope_change={"note": "用户反馈提出的范围变更：数据看板", "node": "code", "signature": "user-feedback"},
            scope_change_approved="用户反馈提出的范围变更：数据看板",
        )
        gen = runner.run(state, "gen-approve")
        # 消费 (无反馈) → 9.3 consume_scope_confirmation 保留 approval →
        # _inject_approved_scope → failure_details 携带确认范围。
        first = await anext(gen)
        assert first["event_type"] != "error"
        instruction = state["failure_details"]["instruction"]
        assert "用户已确认的范围变更" in instruction
        assert "数据看板" in instruction
        await gen.aclose()


# ---------------------------------------------------------------------------
# 10.1 servicer RPC: ReportUserFeedback
# ---------------------------------------------------------------------------


class TestReportUserFeedbackServicer:
    @pytest.mark.asyncio
    async def test_report_user_feedback_disposes(self):
        import grpc
        from ai.v1.generation_pb2 import UserFeedbackRequest

        from app.services.generation.servicer import GenerationServicer

        servicer = GenerationServicer()

        class FakeRunner:
            def __init__(self):
                self._llm_fn = None
                self._pending_feedback = None

        runner = FakeRunner()
        servicer._active_runners["gen-fb-rpc"] = runner
        context = MagicMock(spec=grpc.aio.ServicerContext)

        resp = await servicer.ReportUserFeedback(
            UserFeedbackRequest(generation_id="gen-fb-rpc", stage="code", feedback="缺少订单列表组件"),
            context,
        )
        assert resp.received is True
        assert resp.category == "omission"
        assert resp.result == "dispatched"
        assert runner._pending_feedback["feedback"] == "缺少订单列表组件"

    @pytest.mark.asyncio
    async def test_report_user_feedback_no_runner_aborts_not_found(self):
        import grpc
        from ai.v1.generation_pb2 import UserFeedbackRequest

        from app.services.generation.servicer import GenerationServicer

        servicer = GenerationServicer()
        context = MagicMock(spec=grpc.aio.ServicerContext)
        context.abort = AsyncMock(side_effect=grpc.RpcError("not found"))

        with pytest.raises(grpc.RpcError):
            await servicer.ReportUserFeedback(
                UserFeedbackRequest(generation_id="missing-gen", stage="code", feedback="改一下"),
                context,
            )
        context.abort.assert_awaited_once()
        assert context.abort.call_args[0][0] == grpc.StatusCode.NOT_FOUND

    @pytest.mark.asyncio
    async def test_report_then_run_consumes_end_to_end(self):
        """review fix (E2E): RPC 处置 (真实 runner) → 下次 run 入口消费 —
        重派指令注入 + 处置卡首帧。"""
        import grpc
        from ai.v1.generation_pb2 import UserFeedbackRequest

        from app.services.generation.graph import GraphRunner
        from app.services.generation.servicer import GenerationServicer

        servicer = GenerationServicer()
        runner = GraphRunner(llm_fn=lambda *a: "")
        servicer._active_runners["gen-e2e-fb"] = runner
        context = MagicMock(spec=grpc.aio.ServicerContext)

        resp = await servicer.ReportUserFeedback(
            UserFeedbackRequest(generation_id="gen-e2e-fb", stage="code", feedback="缺少订单列表组件"),
            context,
        )
        assert resp.received is True
        assert resp.category == "omission"

        state = _code_state(generation_id="gen-e2e-fb")
        gen = runner.run(state, "gen-e2e-fb")
        first = await anext(gen)
        assert first["event_type"] == "manager_message"
        assert first["data"]["card"] == "feedback_card"
        assert "缺少订单列表组件" in state["failure_details"]["instruction"]
        assert state["code_result"] is None  # 产物清空 → 重派
        await gen.aclose()


class TestServicerStreamGuard:
    """review fix: 取消保留 runner + resume 无 runner 不静默空跑."""

    @pytest.mark.asyncio
    async def test_cancel_keeps_runner_for_resume(self):
        """停止 (context.cancelled) 后 runner 保留 (反馈→resume 消费处置),
        运行标记清理 (不残留 cancelling/running) — 走真实 _stream_graph finally."""
        import grpc
        from ai.v1.generation_pb2 import GenerateRequest, GenerationConfig, Message

        from app.services.generation.servicer import GenerationServicer

        class FakeRunner:
            def __init__(self):
                self._llm_fn = None
                self._pending_feedback = None

            async def run(self, state, generation_id):
                yield {"event_type": "token", "stage": "analysis", "data": {}}

        fake_runner = FakeRunner()
        servicer = GenerationServicer()
        servicer._active_runners["gen-cancel-x"] = fake_runner
        context = MagicMock(spec=grpc.aio.ServicerContext)
        # 第一次检查 False (yield 事件) → 第二次 True (取消 → break → finally)
        context.cancelled.side_effect = [False, True]

        from unittest.mock import patch

        request = GenerateRequest(
            generation_id="gen-cancel-x",
            model="glm-5.2",
            messages=[Message(role="user", content="做一个页面")],
            config=GenerationConfig(temperature=0.7, max_tokens=100),
            metadata={"mode": "graph"},
        )
        with patch(
            "app.services.generation.servicer.GraphRunner",
            return_value=fake_runner,
        ), patch(
            "app.services.generation.servicer.resolve_provider",
        ) as mock_resolve:
            mock_resolve.return_value = MagicMock()
            responses = []
            async for resp in servicer.StreamGenerate(request, context):
                responses.append(resp)

        assert responses and responses[0].WhichOneof("payload") == "graph_event"
        # 关键断言: 取消后 runner 保留 (TG10 反馈处置消费), 运行标记清理
        assert servicer._active_runners.get("gen-cancel-x") is fake_runner
        assert "gen-cancel-x" not in servicer._active_generations

    @pytest.mark.asyncio
    async def test_resume_no_runner_empty_messages_fails_loudly(self):
        """resume 无 runner + 空消息 → NOT_FOUND 错误事件, 绝不静默空跑."""
        import grpc
        from ai.v1.generation_pb2 import GenerateRequest, GenerationConfig

        from app.services.generation.servicer import GenerationServicer

        servicer = GenerationServicer()
        context = MagicMock(spec=grpc.aio.ServicerContext)
        context.cancelled.return_value = False

        request = GenerateRequest(
            generation_id="gen-lost",
            model="glm-5.2",
            messages=[],
            config=GenerationConfig(temperature=0.7, max_tokens=100),
            metadata={"mode": "resume"},
        )
        responses = []
        async for resp in servicer.StreamGenerate(request, context):
            responses.append(resp)
        assert len(responses) == 1
        assert responses[0].WhichOneof("payload") == "error"
        assert responses[0].error.code == "NOT_FOUND"
        assert "runner" in responses[0].error.message
        # 未创建任何 runner (没有静默重新起跑)
        assert "gen-lost" not in servicer._active_runners

    @pytest.mark.asyncio
    async def test_resume_no_runner_with_content_falls_to_fresh_start(self):
        """resume 无 runner 但带完整消息 (预填产物) → 允许 fresh-start 兜底."""
        import grpc
        from ai.v1.generation_pb2 import GenerateRequest, GenerationConfig, Message

        from app.services.generation.servicer import GenerationServicer

        servicer = GenerationServicer()
        context = MagicMock(spec=grpc.aio.ServicerContext)
        context.cancelled.return_value = False

        request = GenerateRequest(
            generation_id="gen-prefill",
            model="glm-5.2",
            messages=[Message(role="user", content="PRD 全文")],
            config=GenerationConfig(temperature=0.7, max_tokens=100),
            metadata={"mode": "resume", "skip_analysis": "true"},
        )
        responses = []
        async for resp in servicer.StreamGenerate(request, context):
            responses.append(resp)
            break  # 只验证首帧不是错误即可
        assert responses[0].WhichOneof("payload") != "error"


# ---------------------------------------------------------------------------
# review fix: manager_gate 范围注入去重 (resume 入口已注入, gate redo 不重复)
# ---------------------------------------------------------------------------


class TestApprovedScopeInjectionDedupe:
    @pytest.mark.asyncio
    async def test_manager_gate_does_not_duplicate_approved_scope(self):
        """failure_details 已含确认范围 (resume 入口注入) → gate redo 路径
        不再追加 (manager.py 去重守卫), 指令块恰好出现一次。"""
        from app.services.generation.manager import manager_gate

        block = "[用户已确认的范围变更] 数据看板"
        state = _code_state(
            generation_id="gen-dedupe",
            compile_errors=[{"file": "A.vue", "line": 1, "message": "syntax"}],
            failure_details={"instruction": block, "source": "code", "failed_items": [], "rollback_target": "code"},
            scope_change_approved="数据看板",
        )
        out = await manager_gate(state)
        assert out["manager_verdicts"][-1]["decision"] == "redo"
        instruction = out["failure_details"]["instruction"]
        assert instruction.count(block) == 1


# ---------------------------------------------------------------------------
# 10.1 旧路径移除: code_feedback 不再注入 planner 自我审查 prompt
# ---------------------------------------------------------------------------


class TestOldPlannerPathRemoved:
    @pytest.mark.asyncio
    async def test_planner_ignores_code_feedback(self):
        """旧 code-feedback-loop 路径: planner_node 的「用户反馈 → 自我审查
        补充 DAG」块已移除 — code_feedback 不进 planner prompt。"""
        from app.services.generation import nodes

        state = _state(
            generation_id="gen-old-path",
            code_feedback="缺少订单列表组件",
            design_doc="# 设计方案",
            generated_files={"App.vue": "<template>x</template>"},
        )
        captured: dict = {}
        dag_json = json.dumps({"reasoning": "x", "tasks": [
            {"id": "task-0", "type": "business", "description": "t", "deps": [], "files": ["src/App.vue"], "contract": {}},
        ]})

        async def fake_llm(system_prompt, user_content, **kwargs):
            captured["user_prompt"] = user_content
            return dag_json

        queue = asyncio.Queue()
        with patch("app.services.generation.nodes._llm_generate", new_callable=AsyncMock, side_effect=fake_llm):
            result = await nodes.planner_node(state, queue)
        assert result["planner_dag"]["tasks"]
        assert "用户反馈" not in captured["user_prompt"]
        assert "补充 Task DAG" not in captured["user_prompt"]
