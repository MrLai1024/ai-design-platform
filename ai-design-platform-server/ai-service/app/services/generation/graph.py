"""
LangGraph StateGraph — manager-worker (supervisor) orchestration skeleton.

Pipeline: 头脑风暴(future interactive phase) → 需求分析 → 方案设计 → 功能实现 → E2E.
The review node is removed entirely.

Topology (D1):
    entry → manager_gate ──(pass)─────────────────→ e2e → manager_gate ──(pass, e2e passed)──→ END
                        └──(redo / rollback)──→ code → manager_gate ─┘

Every worker node's edge returns to `manager_gate`; the gate runs L1
deterministic checks, writes a verdict into `manager_verdicts`, and routes to
the next worker / rollback / END. Workers never pass artifacts directly to
each other.

NOTE: phases analysis / design / code are NOT LangGraph nodes — they are
implemented manually in GraphRunner.run() (streaming PRD, streaming design
doc, planner+executor loop). Only `manager_gate` and the code/e2e workers run
as real LangGraph nodes (the code worker serves the rollback path).

Phase 3 (5.6): the executor task loop is tier-aware — L 档 runs independent
tasks in parallel batches (`asyncio.gather`, dependency-gated rescan; merge
discipline documented at `_run_pending_tasks`), S/M 档 stays sequential
(byte-identical). After L1-L3 (+Debugger) converge, the L 档 Tester generates
and best-effort-executes unit/component tests as the Verifier's L4 layer;
test failures enter Debugger fix rounds that re-test after each fix.
"""

import json
import time
from functools import partial
from typing import Any, AsyncIterator

from langgraph.graph import StateGraph, END
from langgraph.types import Command
from langgraph.checkpoint.memory import MemorySaver

from .state import GenerationState
from .nodes import (
    code_node,
    e2e_node,
    planner_node,
    executor_task,
    planner_reflect_node,
)
from .manager import (
    evaluate_stage_l2,
    last_design_verdict,
    manager_gate,
    record_verdict,
    run_l1_checks,
)
from .dialog import gate_speech_events
from .harness import LoopControl
from .recovery import rejects_scope_change  # 9.3 范围卡拒绝标记 (I5 收紧)

import structlog

logger = structlog.get_logger()


# Mid-term trajectory (7.5): curated event types archived to SQLite — the
# run trajectory is the event-stream digest, NOT every streamed token.
_TRAJECTORY_EVENT_TYPES = frozenset({
    "stage_start", "stage_complete", "manager_verdict", "human_confirm_required",
    "prd_generate_start", "prd_generate_done", "design_gen_done", "code_gen_done",
    "tier_assessed", "planner_dag", "task_complete", "task_acceptance",
    "compile_status", "verifier_result", "debugger_diagnosis", "debugger_stopped",
    "tester_result", "e2e_cases_gen_done", "e2e_diagnosis", "e2e_complete",
    "loop_break", "error",
})


def _incremental_confirm_card(node: str, content: str) -> dict:
    """8.x 增量确认卡: confirm_card + 选项 [确认, 重新生成] + data 标记
    (前端据此把「重新生成」路由到 runner.regen_incremental_step)。"""
    from .dialog import confirm_card_event

    event = confirm_card_event(node, content, options=["确认", "重新生成"])
    event["data"] = {**event.get("data", {}), "incremental": True}
    return event


def _merge_constraints(state: GenerationState, contract: dict) -> dict:
    """Carry the Manager/user-preference constraints (7.6) into a rebuilt
    dispatch contract — DESIGN_DISPATCH_CONTRACT / build_code_dispatch_contract
    must not drop the servicer-injected preference constraints."""
    prev = list((state.get("dispatch_contract") or {}).get("constraints") or [])
    base = list(contract.get("constraints") or [])
    merged = base + [c for c in prev if c not in base]
    return {**contract, "constraints": merged}


def _constraints_block(state: GenerationState) -> str:
    """Render dispatch constraints (incl. long-term user preferences, 7.6)
    as a prompt block — the consumption point for the injected constraints."""
    constraints = list((state.get("dispatch_contract") or {}).get("constraints") or [])
    if not constraints:
        return ""
    return (
        "## 约束（Manager 分发 + 用户历史偏好，必须遵守）\n"
        + "\n".join(f"- {c}" for c in constraints)
    )


def _evidence_summary(evidence: dict) -> str:
    """Compact one-line summary of verifier evidence (for problem records).

    M4: 委托 recovery.evidence_refs — 证据 → 文本的唯一映射 (与诊断卡共用),
    不再维护第二份映射。
    """
    from .recovery import evidence_refs

    return "；".join(evidence_refs(evidence))


def decide_after_gate(state: GenerationState) -> str:
    """Conditional edge after manager_gate — maps the gate's routing decision.

    The gate itself computes the decision (verdict + ``manager_next``) so the
    routing stays a pure function of state.
    """
    nxt = state.get("manager_next") or "e2e"
    if nxt == "end":
        return END
    if nxt in ("code", "e2e"):
        return nxt
    return "e2e"


def build_graph(llm_fn: Any | None = None) -> StateGraph:
    """Build and return the compiled LangGraph StateGraph.

    ``llm_fn`` threads the LLM seam into the gate node (design L2 evaluation,
    4.4); when None the gate falls back to the singleton ``_llm_generate``
    path, matching brainstorm's provider-threading pattern.
    """
    workflow = StateGraph(GenerationState)

    # Add nodes — manager gate + workers
    gate_node = (
        manager_gate
        if llm_fn is None
        else partial(manager_gate, llm_fn=llm_fn)
    )
    workflow.add_node("manager_gate", gate_node)
    workflow.add_node("code", code_node)
    workflow.add_node("e2e", e2e_node)

    # Entry point — flow always starts at the coordinator gate
    workflow.set_entry_point("manager_gate")

    # Worker edges always return to the gate (D1)
    workflow.add_edge("code", "manager_gate")
    workflow.add_edge("e2e", "manager_gate")

    # Gate routes: next worker / rollback / end
    workflow.add_conditional_edges(
        "manager_gate",
        decide_after_gate,
        {
            END: END,
            "code": "code",
            "e2e": "e2e",
        },
    )

    # User confirmation points: before the code/e2e workers.
    # (review removed; brainstorm confirmation arrives with the agenda engine)
    checkpointer = MemorySaver()
    app = workflow.compile(
        checkpointer=checkpointer,
        interrupt_before=["code", "e2e"],
    )

    return app


class GraphRunner:
    """Runs the LangGraph app and bridges gRPC streaming with frontend SSE."""

    def __init__(self, llm_fn: Any | None = None, memory_db: Any | None = None):
        self.app = build_graph(llm_fn=llm_fn)
        self.loop_control = LoopControl()
        self._state: GenerationState | None = None
        self._active_registry = None  # ToolRegistry of the running code phase
        self._verdicts_emitted = 0    # manager_verdicts already streamed as events
        # LLM seam threaded into the gate (design L2, 4.4); None → singleton.
        self._llm_fn = llm_fn
        # Mid-term memory (7.5): trajectory archive; None → no trajectory.
        self._memory_db = memory_db
        self._generation_id: str | None = None
        # 10.1: RPC (ReportUserFeedback) 处置挂起的用户反馈 — 下次 run/resume
        # 入口消费 (注入重派指令 + 发射处置卡)。
        self._pending_feedback: dict | None = None

    def _e2e_node_events(self, node_output: dict) -> list[dict]:
        """Events for one e2e worker output (task group 6).

        Designer phase (unconfirmed): coverage_matrix card + rendered MD
        summary + DSL case list (``e2e_cases_gen_done.cases`` is the canonical
        artifact, consumed by the frontend). Confirmed pass-through (no
        results yet): ``e2e_execute_start`` handing the DSL cases to the
        frontend runner (which skips ``requires_browser`` cases — 6.7).
        """
        events: list[dict] = []
        if node_output.get("e2e_user_confirmed") and node_output.get("e2e_results") is None:
            cases = node_output.get("e2e_test_cases") or []
            requires_browser = [c["id"] for c in cases if c.get("requires_browser")]
            events.append(self._make_event("e2e_execute_start", "e2e", {
                "test_cases": cases,
                "total": len(cases),
                "requires_browser": requires_browser,
            }))
            return events

        report = node_output.get("e2e_designer_report") or {}
        if report:
            from .dialog import coverage_matrix_event
            payload = report.get("card_payload") or {}
            events.append(coverage_matrix_event(
                "e2e",
                payload.get("matrix") or {},
                content=report.get("card_content") or "",
                extra={k: v for k, v in payload.items() if k != "matrix"},
            ))
            md = report.get("md") or ""
            events.append(self._make_event("e2e_cases_gen_start", "e2e", {}))
            for i in range(0, len(md), 80):
                events.append(self._make_event("doc_chunk", "e2e", {"content": md[i:i + 80]}))
            events.append(self._make_event("e2e_cases_gen_done", "e2e", {
                "full_content": md,
                "cases": report.get("cases") or [],
                "coverage": report.get("coverage") or {},
                "dropped": report.get("dropped") or [],
                "requires_browser": [
                    c["id"] for c in (report.get("cases") or []) if c.get("requires_browser")
                ],
            }))
            return events

        # Legacy fallback: plain MD doc without a designer report.
        e2e_cases_md = node_output.get("e2e_test_cases_md", "")
        if e2e_cases_md:
            events.append(self._make_event("e2e_cases_gen_start", "e2e", {}))
            for i in range(0, len(e2e_cases_md), 80):
                events.append(self._make_event("doc_chunk", "e2e", {"content": e2e_cases_md[i:i + 80]}))
            events.append(self._make_event("e2e_cases_gen_done", "e2e", {
                "full_content": e2e_cases_md,
            }))
        return events

    def report_compile_feedback(self, ok: bool, errors: list[dict] | None = None) -> bool:
        """Receive real bundler compile feedback from the frontend.

        Returns True if a code-phase registry is active to consume it.
        """
        if self._active_registry is None:
            return False
        self._active_registry.report_frontend_compile(ok, errors)
        return True

    def report_runtime_errors(self, errors: list[dict] | None = None) -> bool:
        """Receive preview-iframe runtime errors (Verifier L3 evidence).

        Replace semantics: each batch is the current build's snapshot; the
        frontend sends an empty batch to clear on new loads. Returns True if
        a code-phase registry is active to consume it.
        """
        if self._active_registry is None:
            return False
        self._active_registry.report_runtime_errors(errors)
        return True

    # ── 10.1 用户反馈消费 (run/resume 入口) ──

    def _inject_approved_scope(self, state: dict) -> None:
        """已确认的范围变更 (``scope_change_approved``) → failure_details.instruction
        (code worker 重派指令通道)。

        只在 run() 入口消费 — 手动阶段 gate (_gate_manual_stage) 没有
        manager.py 的 redo 注入点; LangGraph 阶段由 manager_gate (redo) 注入,
        本函数带去重守卫, 双路径共存不重复。
        """
        approved = state.get("scope_change_approved")
        if not approved:
            return
        note = approved if isinstance(approved, str) else ""
        if not note.strip():
            return
        fd = dict(state.get("failure_details") or {})
        instruction = fd.get("instruction", "")
        block = f"[用户已确认的范围变更] {note.strip()}"
        if block in instruction:
            return
        fd["instruction"] = (instruction + "\n" if instruction else "") + block
        fd.setdefault("source", "code")
        fd.setdefault("failed_items", [])
        fd.setdefault("rollback_target", "code")
        state["failure_details"] = fd

    def _pending_feedback_checkpoint_sync(
        self,
        state: dict,
        pending: dict,
        redo_updates: dict,
    ) -> bool:
        """LangGraph 已启动的线程: 把反馈处置同步进 checkpoint.

        Returns True 时调用方必须保留 ``self._state`` 的 ``code_result``
        (resume 走 LangGraph 续跑 — code worker 以清空产物 + 重派指令重跑,
        gate 不会复用旧裁决); False → 无 checkpoint, 调用方清除
        ``self._state`` 产物并走 run() 重跑。
        """
        gid = self._generation_id or state.get("generation_id") or ""
        if not gid:
            return False
        config = {"configurable": {"thread_id": gid}}
        try:
            snap = self.app.get_state(config)
            values = snap.values or {}
            if not values:
                return False
            self.app.update_state(config, redo_updates)
            logger.info(
                "feedback_checkpoint_synced",
                generation_id=gid, category=pending.get("category"),
            )
            return True
        except Exception as e:  # pragma: no cover - fail-open
            logger.warning("feedback_checkpoint_sync_failed", generation_id=gid, error=str(e))
            return False

    async def _consume_pending_feedback(self, state: dict | None) -> tuple[list[dict], bool]:
        """10.1: 消费挂起的用户反馈 — 注入重派指令 / 范围确认, 返回处置卡事件.

        Returns ``(events, halt)``; ``halt=True`` 时调用方必须立即停止
        (范围变更: 等 confirm_card 答复, 不得自行重派)。

        - 遗漏/纠偏 → ``failure_details.instruction`` 注入 (U9 redo 通道) +
          清空当前 code 产物 → 重派执行 (run 重跑 phase 3 / resume 从
          checkpoint 续跑 code worker)。
        - 范围变更 → ``pending_scope_change`` (U9 范围确认机制) + confirm_card;
          用户确认 (resume) 后经 consume_scope_confirmation 批准进入重派反馈。
        - 兜底通道: 网关 metadata ``code_feedback`` 注入 (runner 重建等,
          RPC 未及处置) — 在消费点等价分类 + 记录。
        """
        from .dialog import (
            CARD_CONFIRM,
            confirm_card_event,
            feedback_disposition_card_event,
        )
        from .recovery import SCOPE_OPTIONS

        if state is None:
            return [], False

        pending = self._pending_feedback
        if pending is None:
            # 兜底: metadata code_feedback (fresh start / runner 重建)。
            text = (state.get("code_feedback") or "").strip()
            if not text or rejects_scope_change(text):
                return [], False
            from .feedback import classify_user_feedback, record_feedback_problem

            classification = await classify_user_feedback(
                text, state.get("stage", ""), llm_fn=self._llm_fn
            )
            category = classification["category"]
            if category == "scope_change":
                action, result = "范围变更待确认（confirm_card）", "awaiting_confirm"
            else:
                action, result = "重派功能实现任务（携带反馈）", "dispatched"
            record_feedback_problem(
                state.get("generation_id") or "unknown",
                text, classification, action, result,
            )
            from .feedback import FEEDBACK_CATEGORY_LABELS

            pending = self._pending_feedback = {
                "feedback": text,
                "stage": state.get("stage", ""),
                "category": category,
                "reason": classification["reason"],
                "confidence": classification["confidence"],
                "scope_note": classification.get("scope_note", ""),
                "action": action,
                "result": result,
                "category_label": FEEDBACK_CATEGORY_LABELS.get(category, category),
            }
            state["code_feedback"] = ""  # 消费即清, 防重复处置

        self._pending_feedback = None  # 消费即清 (run/resume 双入口防重复)

        category = pending["category"]
        stage = pending.get("stage") or state.get("stage") or "code"
        events: list[dict] = []

        if category == "scope_change":
            note = (pending.get("scope_note") or pending.get("feedback") or "").strip()
            state["pending_scope_change"] = {
                "note": f"用户反馈提出的范围变更：{note}",
                "node": "code",
                "signature": "user-feedback",
            }
            confirm = confirm_card_event(
                stage,
                f"用户反馈提出新增需求范围，Manager 需你确认后才执行：\n{note}",
                options=list(SCOPE_OPTIONS),
            )
            confirm["data"] = {**confirm.get("data", {}), "scope_confirm": True}
            events.append(feedback_disposition_card_event(stage, pending["feedback"], pending))
            events.append(confirm)
            synced = self._pending_feedback_checkpoint_sync(
                state, pending,
                {"pending_scope_change": state["pending_scope_change"]},
            )
            if not synced:
                # 无 checkpoint (手动阶段暂停) — 清空产物, 用户确认 (resume)
                # 后转 run() 重跑: consume_scope_confirmation 批准 →
                # _inject_approved_scope → 重派指令携带确认范围。
                state["code_result"] = None
                state["generated_files"] = {}
                state["compile_errors"] = None
            logger.info("feedback_scope_change_pending", stage=stage)
            return events, True

        # 遗漏/纠偏 → 重派指令注入 (failure_details.instruction, U9 redo 通道)。
        fd = dict(state.get("failure_details") or {})
        instruction = fd.get("instruction", "")
        block = (
            f"[用户反馈（Manager 处置：{pending.get('category_label', category)}）] "
            f"{pending['feedback']}"
        )
        if pending.get("reason"):
            block += f"\n分类理由：{pending['reason']}"
        fd["instruction"] = (instruction + "\n" if instruction else "") + block
        fd.setdefault("source", "code")
        fd.setdefault("failed_items", [])
        fd.setdefault("rollback_target", "code")
        state["failure_details"] = fd

        redo_updates = {
            "failure_details": fd,
            "code_result": None,
            "generated_files": {},
            "compile_errors": None,
        }
        if self._pending_feedback_checkpoint_sync(state, pending, redo_updates):
            # checkpoint 已同步 — 保留 self._state.code_result, resume 走
            # LangGraph 续跑 (code worker 以清空产物重跑)。
            pass
        else:
            # 无 checkpoint (手动阶段暂停) — 清空产物, resume 转 run() 重跑
            # phase 3 (planner + executor 携带重派指令)。
            # 磁盘覆盖契约 (review): 重派只清内存产物, 磁盘上 project_root 的
            # 文件不删除 — 与既有 U9 redo 语义一致 (executor 以覆盖写为契约,
            # 相同路径重写; 若新计划路径变少, 旧文件残留是既有行为, 由编译/
            # E2E 把关暴露而非静默删除, 避免误删用户文件)。
            state["code_result"] = None
            state["generated_files"] = {}
            state["compile_errors"] = None

        events.append(feedback_disposition_card_event(stage, pending["feedback"], pending))
        logger.info(
            "feedback_redispatch_pending",
            stage=stage, category=category, result=pending.get("result"),
        )
        return events, False

    async def run(
        self,
        state: GenerationState,
        generation_id: str,
    ) -> AsyncIterator[dict]:
        """
        Run the graph, yielding GraphEvent dicts for each state transition.
        PRD is streamed token-by-token before LangGraph takes over.
        """
        self._state = state
        self._generation_id = generation_id
        # 7.1: generation_id 进 state — project_root_for 的 app_id 推导来源,
        # 崩溃恢复/续跑按同一 app_id 找 .ai-memory。
        state["generation_id"] = generation_id
        config = {"configurable": {"thread_id": generation_id}}
        max_iterations = 50
        iteration = 0

        # ── 8.1-8.4 增量开发入口: diff → manifest → 用例处置 (逐级确认) ──
        if state.get("incremental_mode"):
            paused = False
            async for ev in self._run_incremental_entry(state, generation_id):
                yield ev
                paused = True
            if paused:
                return  # 等待用户确认 (resume 后从下一级继续)

        # ── 10.1 用户反馈消费 (run 入口) ──
        # RPC (ReportUserFeedback) 处置挂起的反馈 → 重派指令注入 + 处置卡;
        # 范围变更 → confirm_card (halt, 等用户确认, 不得自行重派)。
        fb_events, fb_halt = await self._consume_pending_feedback(state)
        for ev in fb_events:
            yield ev
        if fb_halt:
            return

        # ── 9.3 求援/范围确认 resume 消费 (手动阶段) ──
        # 「继续自主」→ 重置该问题自主尝试计数后继续; 范围确认卡 resume →
        # 批准范围变更 (进入 design_gate_feedback 的重派反馈)。
        from .recovery import consume_escalation_reset, consume_scope_confirmation

        consume_escalation_reset(state)
        consume_scope_confirmation(state)

        # 10.1: 已确认的范围变更 → code 重派指令 (手动阶段 gate 无注入点)。
        self._inject_approved_scope(state)

        # ── Phase 1: Stream PRD with reasoning in real-time ──
        if not state.get("analysis_result"):
            logger.info("graph_run_phase1_start gen=%s", generation_id)
            import asyncio as _asyncio
            from .nodes import ANALYSIS_PRD_PROMPT, _llm_generate

            from .memory import update_run_context
            update_run_context(state, stage="analysis", phase="generating", active_node="analysis")

            yield self._make_event("stage_start", "analysis", {"phase": "generating"})
            yield self._make_event("prd_generate_start", "analysis", {
                "mode": "full", "sections_count": 6, "parent_version": None,
                "incremental": bool(state.get("incremental_mode") and state.get("change_manifest")),
            })

            requirement = state.get("requirement", "")
            messages = state.get("messages", [])
            # Task group 3 (3.6): PRD consumes the 澄清产物 — structured
            # requirement + decision log + assumptions — when the brainstorm
            # session provided them; otherwise fall back to the raw context.
            requirements_state_json = state.get("requirements_state_json")
            if requirements_state_json:
                try:
                    pretty_req = json.dumps(
                        json.loads(requirements_state_json),
                        ensure_ascii=False, indent=2,
                    )
                except (json.JSONDecodeError, TypeError):
                    pretty_req = requirements_state_json
                prompt_parts = [
                    f"用户需求：{requirement}",
                    "以下为头脑风暴澄清产物（结构化需求 + 决策日志 + 假设清单），请以其为准生成完整的需求规格文档：",
                    f"### 结构化需求（RequirementsState）\n{pretty_req}",
                ]
                decisions = state.get("brainstorm_decisions") or []
                assumptions = state.get("brainstorm_assumptions") or []
                if decisions:
                    prompt_parts.append(
                        "### 决策日志\n"
                        + json.dumps(decisions, ensure_ascii=False, indent=2)
                    )
                if assumptions:
                    prompt_parts.append(
                        "### 假设清单\n"
                        + json.dumps(assumptions, ensure_ascii=False, indent=2)
                    )
                user_prompt = "\n\n".join(prompt_parts)
            else:
                context_parts = []
                for m in messages:
                    context_parts.append(f"[{m.get('role', '?')}]: {m.get('content', '')}")
                context = "\n".join(context_parts)
                user_prompt = f"用户需求：{requirement}\n\n对话上下文：{context}\n\n请生成完整的需求规格文档。"

            # 7.6: 分发约束（含长期用户偏好）消费点 — PRD prompt。
            constraints_block = _constraints_block(state)
            if constraints_block:
                user_prompt += "\n\n" + constraints_block

            # I3: 需求分析把关反馈 (redo 后重跑 PRD 时携带) — 镜像设计阶段
            # design_gate_feedback: 失败理由 + 恢复阶梯反馈进入重生成 prompt。
            from .manager import analysis_gate_feedback

            analysis_feedback = analysis_gate_feedback(state)
            if analysis_feedback:
                user_prompt += (
                    "\n\n## Manager 把关反馈（上一版 PRD 未通过，请据此修正后重新生成）\n"
                    + analysis_feedback
                )

            # 8.3 增量 PRD: 提示词级 delta 框定 — 已有需求规格摘要 + 变更
            # manifest; 输出仍为完整 PRD (下游 Planner/Designer 消费完整文档)。
            if state.get("incremental_mode") and state.get("change_manifest"):
                inc = state.get("incremental_context") or {}
                existing_req = (inc.get("requirements") or "")[:2500]
                user_prompt += (
                    "\n\n## 增量开发上下文（重要）\n"
                    "这是对已有应用的**增量开发**。"
                    + (f"已有需求规格（摘要）：\n{existing_req}\n\n" if existing_req else "")
                    + "### 变更 manifest\n"
                    + json.dumps(state.get("change_manifest"), ensure_ascii=False, indent=2)
                    + "\n\n## 增量 PRD 要求\n"
                    "- 输出**完整**的需求规格文档（下游需要完整文档），但内容聚焦本次变更：\n"
                    "  - 「## 2. 功能模块」保留已有功能点，标注本次新增/修改的功能点\n"
                    "  - 「## 5. 交互行为」优先描述变更后的行为（from → to）\n"
                    "- 未变更的功能与已有规格保持一致，不得遗漏"
                )

            # Use a queue to stream reasoning + tokens in real-time
            event_queue: _asyncio.Queue = _asyncio.Queue()

            def on_reasoning(text: str):
                event_queue.put_nowait(("reasoning", text))

            def on_token(text: str):
                event_queue.put_nowait(("token", text))

            async def generate_prd():
                return await _llm_generate(
                    system_prompt=ANALYSIS_PRD_PROMPT,
                    user_content=user_prompt,
                    enable_thinking=True,
                    on_reasoning=on_reasoning,
                    on_token=on_token,
                )

            gen_task = _asyncio.create_task(generate_prd())

            # Stream events while LLM is generating
            while not gen_task.done() or not event_queue.empty():
                try:
                    _type, text = await _asyncio.wait_for(event_queue.get(), timeout=0.1)
                    if _type == "reasoning":
                        yield self._make_event("prd_reasoning", "analysis", {"text": text})
                    elif _type == "token":
                        yield self._make_event("doc_chunk", "analysis", {
                            "content": text,
                        })
                except _asyncio.TimeoutError:
                    pass  # no event yet, keep waiting

            prd_full = gen_task.result()
            state["analysis_result"] = prd_full

            yield self._make_event("prd_section_complete", "analysis", {"section_key": "content"})
            yield self._make_event("prd_generate_done", "analysis", {
                "version": 1, "full_content": prd_full, "duration_ms": 0,
            })
            yield self._make_event("stage_complete", "analysis", {
                "summary": prd_full[:200] if prd_full else "",
            })
            gate_events = await self._gate_manual_stage(state, "analysis")
            for ev in gate_events:
                yield ev
            analysis_verdict = gate_events[0]["data"]["decision"] if gate_events else "redo"
            if analysis_verdict != "pass":
                # I3: 把关未通过 → 清空 PRD 产物, resume 后阶段 1 带反馈重跑
                # (镜像设计阶段的 redo 语义), 流水线停在此处等待修复 —
                # 失败的 PRD 绝不静默进入方案设计。
                state["analysis_result"] = None
                logger.warning(
                    "analysis_redo_cleared_outputs",
                    reason=gate_events[0]["data"]["reason"] if gate_events else "",
                )
            yield self._make_event("human_confirm_required", "analysis", {
                "message": "Please review the analysis output.",
            })
            return  # Wait for user to click "下一步"

        else:
            logger.info("graph_run_phase1_skip gen=%s reason=analysis_result_already_set", generation_id)

        # ── Phase 2: Stream design doc (same streaming pattern as PRD) ──
        # I3 defense-in-depth: 崩溃恢复/旧产物下失败的 PRD 不得进入设计 —
        # 清空并停等阶段 1 带反馈重跑 (正常 redo 流已在阶段 1 清空并返回)。
        from .manager import last_analysis_verdict

        last_analysis = last_analysis_verdict(state)
        if last_analysis and last_analysis.get("decision") in ("redo", "rollback"):
            if state.get("analysis_result"):
                state["analysis_result"] = None
                yield self._make_event("error", "analysis", {
                    "reason": "需求规格未通过 Manager 把关（redo），已清空产物等待重新生成。",
                })
                return
        if not state.get("design_result"):
            import asyncio as _asyncio
            from .manager import design_gate_feedback
            from .nodes import (
                DESIGN_SYSTEM_PROMPT,
                _llm_generate,
                generate_architecture_spec,
            )
            from .state import DESIGN_DISPATCH_CONTRACT

            from .memory import update_run_context
            update_run_context(state, stage="design", phase="generating", active_node="design")

            yield self._make_event("stage_start", "design", {"phase": "generating"})
            yield self._make_event("design_gen_start", "design", {})

            # 4.x: dispatch contract for the design worker (D3) — the Manager
            # gates against these acceptance criteria (L1 + L2, 4.3/4.4).
            # 7.6: 携带已注入的分发约束（长期用户偏好）— 不得被默认契约丢弃。
            state["dispatch_contract"] = _merge_constraints(state, dict(DESIGN_DISPATCH_CONTRACT))

            # Review fix 1: when the design gate failed on a previous run, the
            # outputs were cleared and the redo reason (L1 field list / L2
            # missing list) is fed back into the regeneration prompts.
            redo_feedback = design_gate_feedback(state)
            prompt = f"需求分析文档：\n{state.get('analysis_result', '')}"
            constraints_block = _constraints_block(state)
            if constraints_block:
                prompt += "\n\n" + constraints_block  # 7.6 约束消费点
            if redo_feedback:
                prompt += (
                    "\n\n## Manager 把关反馈（上一版方案未通过，请据此修正后重新设计）\n"
                    + redo_feedback
                )

            event_queue: _asyncio.Queue = _asyncio.Queue()

            def _dr(text: str):
                event_queue.put_nowait(("reasoning", text))

            def _dt(text: str):
                event_queue.put_nowait(("token", text))

            async def _gen_design():
                return await _llm_generate(
                    system_prompt=DESIGN_SYSTEM_PROMPT,
                    user_content=prompt,
                    enable_thinking=True,
                    on_reasoning=_dr,
                    on_token=_dt,
                )

            gen_task = _asyncio.create_task(_gen_design())

            while not gen_task.done() or not event_queue.empty():
                try:
                    _type, text = await _asyncio.wait_for(event_queue.get(), timeout=0.1)
                    if _type == "reasoning":
                        yield self._make_event("prd_reasoning", "design", {"text": text})
                    elif _type == "token":
                        yield self._make_event("doc_chunk", "design", {"content": text})
                except _asyncio.TimeoutError:
                    pass

            design_full = gen_task.result()
            state["design_result"] = design_full
            state["design_doc"] = design_full
            state["stage_phase"] = "complete"

            # 4.2: machine-readable architecture Spec — second structured LLM
            # call with the D5 schema, validated before acceptance (invalid →
            # one redo with the validation errors; the gate decides after).
            # 8.3 增量设计: 已有架构 Spec 摘要并入 prompt, 输出合并后的完整 Spec。
            existing_spec = None
            if state.get("incremental_mode"):
                existing_spec = (state.get("incremental_context") or {}).get("spec")
            spec, spec_errors = await generate_architecture_spec(
                prd=state.get("analysis_result", ""),
                state=state,
                llm_fn=self._llm_fn,
                feedback=redo_feedback,
                existing_spec=existing_spec if isinstance(existing_spec, dict) else None,
            )
            state["architecture_spec"] = spec
            if spec_errors:
                logger.warning("design_spec_invalid", errors=spec_errors)

            yield self._make_event("design_gen_done", "design", {
                "full_content": design_full,
            })
            yield self._make_event("stage_complete", "design", {
                "summary": design_full[:200] if design_full else "",
            })
            gate_events = await self._gate_manual_stage(state, "design")
            for ev in gate_events:
                yield ev

            design_verdict = gate_events[0]["data"]["decision"] if gate_events else "redo"
            if design_verdict != "pass":
                # Review fix 1: a redo verdict must NOT advance — clear the
                # dual product so the resume path re-runs phase 2 with the
                # gate's feedback. The flow pauses here for human confirm.
                state["design_result"] = None
                state["design_doc"] = None
                state["architecture_spec"] = None
                logger.warning(
                    "design_redo_cleared_outputs",
                    reason=gate_events[0]["data"]["reason"] if gate_events else "",
                )

            yield self._make_event("human_confirm_required", "design", {
                "message": "Please review the design output.",
            })
            return  # Wait for user to click "下一步"

        # ── Phase 3: Planner + Executor ReAct (streaming) ──
        last_design = last_design_verdict(state)
        if last_design and last_design.get("decision") in ("redo", "rollback"):
            # Defense in depth (review fix 1): the code phase must not run on
            # an unverified design. Phase 2 clears the dual product on a redo
            # verdict, so a failed design verdict here means stale outputs —
            # clear them so the resume path re-runs phase 2 with the feedback.
            state["design_result"] = None
            state["design_doc"] = None
            state["architecture_spec"] = None
            yield self._make_event("error", "design", {
                "reason": "设计方案未通过 Manager 把关（redo），已清空产物等待重新设计。",
            })
            return
        if not state.get("generated_files"):
            import asyncio as _asyncio
            from .tools.registry import ToolRegistry
            import os as _os, json as _json, re
            from .tier import assess_complexity_detail, build_code_dispatch_contract
            from .memory import project_root_for, update_run_context

            # 7.1: persistent project root (data/generated/<app_id>) — the
            # runtime state (registry cache, generated files) lives with it.
            _safe_name = re.sub(r'[^\w]', '_', (state.get("requirement", "project"))[:30])[:30].strip('_') or "ai-gen-project"
            project_root = project_root_for(state)
            update_run_context(state, stage="code", phase="planning", active_node="planner")

            registry = ToolRegistry(project_root)
            self._active_registry = registry

            # 8.3 增量实现: 磁盘扫描装载已有文件 (排除 .ai-memory/e2e/node_modules)
            # → registry 缓存 + incremental_context; Planner 只产受影响模块的
            # delta 任务, Verifier 校验全项目 (untouched 模块回归 = 编译+契约)。
            incremental = bool(state.get("incremental_mode") and state.get("change_manifest"))
            existing_files: dict[str, str] = {}
            if incremental:
                from .memory import scan_generated_files

                existing_files = scan_generated_files(project_root)
                state["incremental_context"] = {
                    **(state.get("incremental_context") or {}),
                    "generated_files": existing_files,
                }
                registry.set_generated_files(existing_files)
                logger.info(
                    "code_phase_incremental_files_loaded",
                    existing=len(existing_files),
                )

            # ── 5.1: 复杂度分档（S/M/L，rule-based）→ 角色配置进 dispatch ──
            spec = state.get("architecture_spec")
            tier, tier_reasons = assess_complexity_detail(
                spec,
                state.get("design_doc") or state.get("design_result", ""),
            )
            state["implementation_tier"] = tier
            # 7.6: 携带已注入的分发约束（长期用户偏好）— 不得被分档契约丢弃。
            state["dispatch_contract"] = _merge_constraints(
                state,
                build_code_dispatch_contract(tier, has_spec=bool(spec)),
            )
            logger.info("implementation_tier_assessed", tier=tier, reasons=tier_reasons)
            # Additive event (frontend shows it if handled, ignores otherwise).
            yield self._make_event("tier_assessed", "code", {
                "tier": tier,
                "reasons": tier_reasons,
            })

            yield self._make_event("stage_start", "code", {"phase": "planning"})

            event_queue: _asyncio.Queue = _asyncio.Queue()

            # ── Step 1: Planner → Task DAG ──
            gen_task = _asyncio.create_task(planner_node(state, event_queue))

            while not gen_task.done() or not event_queue.empty():
                try:
                    evt = await _asyncio.wait_for(event_queue.get(), timeout=0.1)
                    yield self._track_event(evt)  # 7.5: planner 事件过轨迹归档
                except _asyncio.TimeoutError:
                    pass

            state = gen_task.result()
            dag = state.get("planner_dag", {})
            tasks = dag.get("tasks", [])

            # 8.3 (review I3): 增量模式确定性过滤 —— 提示词约束是软约束,
            # 这里剔除落在受影响模块之外且已存在的存量文件 + 跨任务重复文件,
            # 防止 delta 任务误覆盖未受影响模块。
            if incremental:
                from .incremental import filter_delta_tasks

                tasks = filter_delta_tasks(
                    tasks,
                    existing_files,
                    (state.get("change_manifest") or {}).get("affected_modules") or [],
                )
                dag["tasks"] = tasks
                state["planner_dag"] = dag

            if not tasks:
                yield self._make_event("error", "code", {"reason": "Planner produced no tasks"})
                return

            generated_files: dict[str, str] = {}
            if incremental:
                # 8.3: 已有文件是执行上下文 — 本地 dict 以已有文件为基座,
                # executor 增量合并新/改文件, 全项目 Verifier 据此校验。
                generated_files = dict(existing_files)
                state["generated_files"] = generated_files
            all_compile_errors: list[dict] | None = None
            max_planner_rounds = 3

            # 5.6 (L 档): 并行 Executor —— 无依赖任务并发执行（批次 gather）。
            # S/M 档保持顺序执行（字节级等同旧循环）。
            parallel = tier == "L"

            # ── Helpers: run one executor task / one planner reflect pass ──
            # (collected events are yielded in-order by the caller — behavior
            # identical to the previous inline drain, and the 5.5 fix rounds
            # reuse the executor runner.)
            def _deps_ok(task: dict) -> bool:
                return all(
                    any(
                        dt["id"] == dep_id and dt.get("status") == "done"
                        for dt in tasks
                    )
                    for dep_id in task.get("deps", [])
                )

            async def _run_executor(task: dict) -> tuple[dict, list[dict]]:
                task["status"] = "running"
                # 并行纪律 (5.6): 任务启动时以共享 generated_files 整包快照
                # （同一 dict 引用，并发启动幂等）；任务中途的写由 executor
                # 走 registry.merge_generated_files 合并，绝不中途全量替换。
                registry.set_generated_files(generated_files)
                state["generated_files"] = generated_files
                exec_queue: _asyncio.Queue = _asyncio.Queue()
                gen = _asyncio.create_task(
                    executor_task(state, task, exec_queue, project_root, registry)
                )
                events: list[dict] = []
                while not gen.done() or not exec_queue.empty():
                    try:
                        evt = await _asyncio.wait_for(exec_queue.get(), timeout=0.1)
                        events.append(self._track_event(evt))  # 7.5: executor 事件过轨迹归档
                    except _asyncio.TimeoutError:
                        pass
                return await gen, events

            async def _planner_reflect() -> tuple[dict, list[dict]]:
                state["generated_files"] = generated_files
                reflect_queue: _asyncio.Queue = _asyncio.Queue()
                gen = _asyncio.create_task(planner_reflect_node(state, reflect_queue))
                events: list[dict] = []
                while not gen.done() or not reflect_queue.empty():
                    try:
                        evt = await _asyncio.wait_for(reflect_queue.get(), timeout=0.1)
                        events.append(self._track_event(evt))  # 7.5: reflect 事件过轨迹归档
                    except _asyncio.TimeoutError:
                        pass
                return await gen, events

            async def _merge_task_result(task: dict, result: dict) -> None:
                """Merge one executor result into the shared phase-3 state."""
                nonlocal all_compile_errors
                task["status"] = result["status"]
                task["executor_summary"] = result["summary"]
                task["compile_errors"] = result["compile_errors"]
                # 5.3: 任务级验收（文件清单 + 契约 + 编译）落到 task 上，
                # planner_reflect_node 据此将 contract_ok=False 判为失败。
                task["acceptance"] = result.get("acceptance")
                # 5.6: 任务内删除的文件从共享状态移除（先删后写 —— 同一任务
                # 内删除再重建的文件在 result["generated_files"] 中重新加入）。
                for path in result.get("deleted_files", []):
                    generated_files.pop(path, None)
                for path, content in result.get("generated_files", {}).items():
                    generated_files[path] = content
                    # Also write to disk
                    full_path = _os.path.join(project_root, path)
                    _os.makedirs(_os.path.dirname(full_path), exist_ok=True)
                    with open(full_path, "w", encoding="utf-8") as wf:
                        wf.write(content)
                if result.get("compile_errors"):
                    all_compile_errors = result["compile_errors"]
                # Update state for context management
                dag["completed_tasks"] = sum(
                    1 for t in tasks if t.get("status") in ("done", "failed")
                )
                state["planner_dag"] = dag
                state["generated_files"] = generated_files
                state["context_summary"] = state.get("context_summary", {"key_exports": {}, "completed_tasks": []})

            async def _run_pending_tasks() -> list[dict]:
                """Execute the runnable pending tasks of one planner round.

                并行纪律 (5.6, documented): executors 共享 phase-3 的
                ``generated_files`` dict 与 registry 缓存。asyncio 是协作式的
                —— 风险在于 await 交错，而非线程。纪律三则:
                1. 每个 executor 启动时对共享 dict 做整包快照
                   （``set_generated_files``，并发启动时同一 dict 引用，幂等）;
                2. 任务中途写缓存只做**逐路径合并**（``merge_generated_files(
                   {path: content})`` / ``remove_generated_file``），绝不中途
                   全量替换 —— 否则并发任务会互相清掉对方在途写入的缓存条目，
                   或把同批已写入的路径回退成旧值（review M1）;
                3. runner 在批次结束后**原子**合并每个任务的结果
                   （``_merge_task_result`` 同步执行，读取与写入之间无 await），
                   并移除 ``deleted_files``。
                最终状态因此一致；缓存对同批任务的在途路径可能瞬时读旧
                （per-path merge 不回退并发写入的路径，但读取方可能看到其它
                任务正在写入路径的旧值）—— 已接受的权衡，文档化。

                L 档: 批次 = 所有 deps 已就绪的 pending 任务，``asyncio.gather``
                并发执行；批次完成后重新扫描（新解锁的依赖任务进下一批次），
                直到无可运行任务。S/M 档: 单遍顺序执行（列表序 + 实时 deps 门），
                与旧循环字节级一致。事件按任务（列表序）整段产出 —— 并行批次
                内 task_start/task_complete 的实际交错不体现在事件流中（文档化）。
                """
                collected: list[dict] = []
                if not parallel:
                    pending = [t for t in tasks if t.get("status") in ("pending", None)]
                    for task in pending:
                        if not _deps_ok(task):
                            continue  # Skip — dependencies not yet done
                        result, exec_events = await _run_executor(task)
                        collected.extend(exec_events)
                        await _merge_task_result(task, result)
                    return collected
                while True:
                    runnable = [
                        t for t in tasks
                        if t.get("status") in ("pending", None) and _deps_ok(t)
                    ]
                    if not runnable:
                        break
                    results = await _asyncio.gather(*(_run_executor(t) for t in runnable))
                    for task, (result, exec_events) in zip(runnable, results):
                        collected.extend(exec_events)
                        await _merge_task_result(task, result)
                return collected

            for planner_round in range(max_planner_rounds):
                # ── Step 2: Execute each pending task（L 档并行 / S/M 顺序） ──
                exec_events = await _run_pending_tasks()
                for ev in exec_events:
                    yield ev

                # ── Step 3: Planner REFLECT ──
                state, reflect_events = await _planner_reflect()
                for ev in reflect_events:
                    yield ev

                # Check exit conditions
                if state.get("stage_phase") == "complete":
                    break  # All done, all passed

                # If still pending tasks, loop back
                still_pending = any(
                    t.get("status") in ("pending", "running", None)
                    for t in state.get("planner_dag", {}).get("tasks", [])
                )
                if not still_pending:
                    break  # All tasks processed (some may have failed)

            # Final compilation check
            compile_result = await registry.invoke("compile_project", {})
            compile_ok = compile_result.ok
            errors = compile_result.data.get("errors", []) if not compile_ok else []
            all_compile_errors = errors if not compile_ok else None

            yield self._make_event("compile_status", "code", {
                "ok": compile_ok,
                "errors": errors,
            })

            # Review fix (Critical): code_result 必须在 Verifier 之前落盘 ——
            # run_verifier 用它打 output_signature，gate 比对同一份输出判定
            # verdict 是否 stale（code_node 重新生成后签名变化 → 不再复用）。
            state["generated_files"] = generated_files
            state["code_result"] = _json.dumps(generated_files, ensure_ascii=False)

            # ── 5.4/5.5/5.6: Verifier 四层验证 + Debugger 证据链修复 + Tester ──
            # Verifier 在 executor 轮次之后、Manager 把关之前运行；失败时
            # Debugger 最多修复 2 轮（证据签名无进展检测），仍失败则交由
            # Manager 把关（redo + 证据 diagnosis card）。L 档的 Tester 在
            # L1-L3（+Debugger）收敛后运行，作为 Verifier 的 L4 行为层。
            from .verifier import evidence_signature, run_verifier
            from .debugger import (
                MAX_FIX_ROUNDS,
                apply_fix_round,
                diagnose,
                no_progress,
                record_round,
            )
            from .tier import TIER_ACCEPTANCE
            from .tester import run_tester

            roles = (
                (state.get("dispatch_contract") or {}).get("roles")
                or TIER_ACCEPTANCE.get(tier, {}).get("roles", [])
            )
            has_debugger = "debugger" in roles
            has_tester = "tester" in roles

            async def _verify_and_report() -> dict:
                result = await run_verifier(state, registry, tier=tier)
                state["verifier_result"] = result
                return result

            async def _fix_round() -> tuple[bool, list[dict]]:
                """一轮 Debugger 修复：诊断 → 重派 → 重跑 → (重测) → 重新验证。

                返回 (通过?, 事件列表)。无进展检测在轮首（证据签名未变化 →
                debugger_stopped 事件，交 Manager 把关）。L 档已生成测试时
                每轮修复后重跑 Tester（L4 证据随代码更新）。
                """
                nonlocal verifier_result, all_compile_errors
                round_no = len(state.get("debugger_rounds") or []) + 1
                evidence = verifier_result.get("evidence") or {}
                signature = evidence_signature(evidence)
                if no_progress(state, signature):
                    # 无进展检测（5.5）：证据未变化 → 停止自动修复，
                    # 升级 Manager 把关（gate redo 带证据）。
                    logger.warning(
                        "debugger_no_progress",
                        round=round_no, signature=signature,
                    )
                    return False, [self._make_event("debugger_stopped", "code", {
                        "reason": "证据未变化（无进展检测）：修复未产生进展，交由 Manager 把关",
                        "signature": signature,
                    })]

                diagnosis = await diagnose(state, evidence, self._llm_fn)
                record_round(state, signature, diagnosis)
                affected_ids = apply_fix_round(state, diagnosis)
                events: list[dict] = [self._make_event("debugger_diagnosis", "code", {
                    "round": round_no,
                    "root_cause": diagnosis.get("root_cause", ""),
                    "fix_instructions": diagnosis.get("fix_instructions", ""),
                    "affected_files": diagnosis.get("affected_files", []),
                    "affected_tasks": affected_ids,
                })]

                # 重派受影响任务 —— Review fix (Important)：与主循环
                # 一致的 deps_ok 门（consumer 等 provider 先完成），
                # 稳定迭代直到一轮无任务可执行（依赖未就绪的保持 pending，
                # 由随后的重新验证给出证据）。
                recompiled = False
                while True:
                    progressed = False
                    for task in list(tasks):
                        if task.get("status") != "pending":
                            continue
                        if not _deps_ok(task):
                            continue  # 依赖未就绪，等下一轮
                        result, exec_events = await _run_executor(task)
                        events.extend(exec_events)
                        await _merge_task_result(task, result)
                        recompiled = True
                        progressed = True
                    if not progressed:
                        break

                # 重新编译 + 重新验证（code_result 刷新后再验证，签名
                # 与 gate 比对的最新输出一致）
                if recompiled:
                    compile_result = await registry.invoke("compile_project", {})
                    compile_ok = compile_result.ok
                    errors = compile_result.data.get("errors", []) if not compile_ok else []
                    all_compile_errors = errors if not compile_ok else None
                    state["compile_errors"] = all_compile_errors
                    events.append(self._make_event("compile_status", "code", {
                        "ok": compile_ok,
                        "errors": errors,
                    }))
                state["code_result"] = _json.dumps(generated_files, ensure_ascii=False)

                # 5.6: 修复后重测 —— L4 证据随代码更新（无测试产物则跳过）。
                if has_tester and (state.get("tester_result") or {}).get("generated"):
                    tester_result = await run_tester(state, project_root, self._llm_fn)
                    state["tester_result"] = tester_result
                    events.append(self._make_event("tester_result", "code", tester_result))

                verifier_result = await _verify_and_report()
                events.append(self._make_event("verifier_result", "code", verifier_result))
                # 7.3: 修复闭环留痕 — problems.jsonl + 中期/长期记忆 (fail-open)。
                passed = verifier_result["passed"]
                self._record_problem(
                    state,
                    category="fix_round",
                    problem=f"验证失败（第 {round_no} 轮修复）: {_evidence_summary(evidence)}",
                    root_cause=diagnosis.get("root_cause", ""),
                    fix=diagnosis.get("fix_instructions", ""),
                    result="passed" if passed else "still_failing",
                )
                return passed, events

            async def _fix_until_pass() -> AsyncIterator[dict]:
                """Debugger 修复轮：最多 MAX_FIX_ROUNDS 轮，通过即停（产事件）。

                注意（5.6 review M2）：修复轮的重派是**顺序**执行的（即使
                L 档）—— 并行只用于初始生成批次；顺序 + deps_ok 门保证证据链
                的确定性重跑顺序（consumer 等 provider 先完成）。
                """
                for _ in range(MAX_FIX_ROUNDS):
                    passed, fix_events = await _fix_round()
                    for ev in fix_events:
                        yield ev
                    if passed:
                        return

            verifier_result = await _verify_and_report()
            yield self._make_event("verifier_result", "code", verifier_result)
            if not verifier_result["passed"]:
                # 7.3: Verifier 失败留痕 (fail-open)。
                self._record_problem(
                    state,
                    category="verifier_failure",
                    problem=f"Verifier 四层验证失败: {_evidence_summary(verifier_result.get('evidence') or {})}",
                    result="escalated_to_debugger" if has_debugger else "escalated_to_manager",
                )

            # Debugger 修复轮（L1-L3 失败 / 已执行测试的 L4 失败）
            if not verifier_result["passed"] and has_debugger:
                async for _ev in _fix_until_pass():
                    yield _ev

            # Tester (5.6): L4 行为层 —— L1-L3 (+Debugger) 收敛后运行（仅 L 档）。
            # 只要 Tester 运行过就重新验证把 L4 并入裁决 —— 测试失败即 L4 失败
            # （进 Debugger 修复轮并每轮重测）；零测试产物（LLM fail-safe 空 /
            # 路径被拒）与执行不可行（deferral）都记为 l4_pending 而非静默通过，
            # 诚实语义见 tester.py / verifier.py / manager.L4_PENDING_NOTE。
            if verifier_result["passed"] and has_tester and not state.get("tester_result"):
                tester_result = await run_tester(state, project_root, self._llm_fn)
                state["tester_result"] = tester_result
                yield self._make_event("tester_result", "code", tester_result)
                if tester_result is not None:
                    verifier_result = await _verify_and_report()
                    yield self._make_event("verifier_result", "code", verifier_result)
                    if not verifier_result["passed"] and has_debugger:
                        async for _ev in _fix_until_pass():
                            yield _ev

            if not verifier_result["passed"]:
                logger.warning(
                    "verifier_failed_escalate",
                    tier=tier, signature=evidence_signature(verifier_result.get("evidence") or {}),
                )

            state["generated_files"] = generated_files
            state["compile_errors"] = all_compile_errors
            state["code_result"] = _json.dumps(generated_files, ensure_ascii=False)
            state["stage_phase"] = "complete"

            yield self._make_event("code_gen_done", "code", {
                "total_files": len(generated_files),
                "compile_errors": len(all_compile_errors) if all_compile_errors else 0,
                "app_name": _safe_name,
                "app_port": 8100 + (hash(_safe_name) % 100),
                # 5.6 review I1: L4 deferral 对前端可见（非失败，仅说明性标志；
                # gate 裁决理由另有 L4_PENDING_NOTE 文字说明）。
                "l4_pending": bool((state.get("verifier_result") or {}).get("l4_pending")),
            })

            yield self._make_event("stage_complete", "code", {
                "summary": f"Generated {len(generated_files)} files in {len(tasks)} tasks",
            })
            for ev in await self._gate_manual_stage(state, "code"):
                yield ev
            yield self._make_event("human_confirm_required", "code", {
                "message": "Please review the code output.",
            })
            return

        # ── Phase 4: Run LangGraph — manager gate + code/e2e workers ──
        confirm_emitted = False
        async for event in self.app.astream(state, config):
            iteration += 1
            # capture the worker node being judged so the loop_break event
            # carries a real stage (the 求援 card needs it, task group 2.5)
            active_node = next((n for n in event if not n.startswith("__")), "")
            if iteration > max_iterations:
                yield self._make_event("loop_break", active_node, {
                    "reason": f"Exceeded max iterations ({max_iterations})",
                })
                break

            for node_name, node_output in event.items():
                # langgraph may yield control events (e.g. {'__interrupt__': ()})
                if node_name.startswith("__"):
                    continue
                # manager_gate: emit verdicts; no stage events (it is not a worker)
                if node_name == "manager_gate":
                    for v in self._manager_verdict_events(node_output):
                        yield v
                    continue

                # 7.4: run_context 随阶段切换更新 (写透到暂存区, fail-open)。
                from .memory import update_run_context
                update_run_context(node_output, stage=node_name, phase="generating", active_node=node_name)

                yield self._make_event("stage_start", node_name, {"phase": "generating"})

                if node_name in ("code", "e2e"):
                    # Confirmed e2e pass-through hands over to the frontend
                    # runner — no second confirm prompt (group 6).
                    if not (node_name == "e2e" and node_output.get("e2e_user_confirmed")):
                        confirm_emitted = True
                        yield self._make_event("human_confirm_required", node_name, {
                            "message": f"Please review the {node_name} output and confirm to continue.",
                        })

                yield self._make_event("stage_complete", node_name, {
                    "summary": self._get_summary(node_name, node_output),
                })

                if node_name == "e2e":
                    for ev in self._e2e_node_events(node_output):
                        yield ev

        # If the gate paused at a worker without a pending confirmation
        # (e.g. first entry), announce it so the frontend can drive on.
        async for ev in self._announce_paused_worker(config, confirm_emitted):
            yield ev

    async def resume(
        self,
        generation_id: str,
        e2e_confirmed: bool = False,
        code_feedback: str = "",
    ) -> AsyncIterator[dict]:
        """Resume the graph from its last interrupt point.

        Called after user clicks [下一步 ▸] to confirm a stage.
        ``e2e_confirmed`` (group 6): an EXPLICIT confirmation of the designed
        E2E cases — only the E2EStagePanel 确认按钮 path sends it (the
        frontend includes the flag in the resume request); chat-intent
        ``proceed`` resumes WITHOUT it, so cases can never be auto-confirmed
        without review. The first e2e entry (no cases yet) is not a
        confirmation either — the Designer runs.

        ``code_feedback`` (task group 9): the gateway-injected pending feedback
        text — a scope-card 「重新生成/取消」 answer REJECTS the pending scope
        change (it never self-applies); any other resume approves it.
        """
        # ── 10.1 用户反馈消费 (resume 入口) ──
        # RPC 处置挂起的反馈 → 重派指令注入 + 处置卡; 范围变更 → confirm_card
        # (halt — 等用户确认后下次 resume 才执行重派)。
        fb_events, fb_halt = await self._consume_pending_feedback(self._state)
        for ev in fb_events:
            yield ev
        if fb_halt:
            return

        # 9.3 范围卡拒绝 (手动阶段): 「重新生成/取消」→ 清除待确认标记, 不批准。
        if (
            rejects_scope_change(code_feedback)
            and self._state
            and self._state.get("pending_scope_change")
        ):
            self._state.pop("pending_scope_change", None)
            logger.info("recovery_scope_change_rejected", feedback=code_feedback[:40])

        # If we haven't reached LangGraph Phase 4 yet (code not generated),
        # re-run manual phases — run() will skip completed phases.
        if self._state and not self._state.get("code_result"):
            async for event in self.run(self._state, generation_id):
                yield event
            return

        self._generation_id = generation_id
        config = {"configurable": {"thread_id": generation_id}}

        # 11.2 (review fix): 手动阶段 (1-3) 不触碰 LangGraph checkpoint —
        # 首次进入 phase 4 的 resume 若直接 astream(Command(resume=True)),
        # langgraph 会在**空线程**上从空 state 静默重跑 (gate 判空产物 redo,
        # 产物全丢)。空 checkpoint + 已有 code 产物 = 手动阶段刚完成 →
        # 回退 run(): 跳过已完成阶段, 以 astream(state) 创建 checkpoint 进入
        # phase 4 (与 run() 首进 phase 4 的语义一致)。
        try:
            snap = self.app.get_state(config)
            thread_started = bool(snap.values)
        except Exception as e:  # pragma: no cover - fail-open
            logger.warning("resume_checkpoint_probe_failed", error=str(e))
            thread_started = False
        if not thread_started and self._state is not None:
            # (review nit): 空 checkpoint + 无 state (fresh runner 误调 resume)
            # 不进入回退 — 有 state 才能续跑; 无 state 时下方 LangGraph 路径
            # 保持原语义 (servicer 正常流程不会到达, 防御性守卫)。
            logger.info("resume_phase4_fallback_run", generation_id=generation_id)
            async for event in self.run(self._state, generation_id):
                yield event
            return

        # ── 9.3 求援/范围确认 resume 消费 (LangGraph checkpoint 内标记) ──
        # 「继续自主」→ 重置该问题自主尝试计数; 范围确认卡 resume → 批准
        # 范围变更 (design_gate_feedback 消费); 「重新生成/取消」→ 拒绝。
        # fail-open, 绝不阻断 resume。
        try:
            snap = self.app.get_state(config)
            values = snap.values or {}
            updates: dict = {}
            if values.get("escalated_signature"):
                from .recovery import consume_escalation_reset

                probe = dict(values)
                if consume_escalation_reset(probe):
                    # 「继续自主」重置: 问题尝试计数 + LoopControl 回退计数 +
                    # 最近裁决的 escalate 标记 (防 reuse 死循环)。
                    updates["escalated_signature"] = None
                    updates["problem_attempts"] = probe.get("problem_attempts")
                    updates["rollback_count"] = probe.get("rollback_count") or {}
                    updates["rollback_records"] = probe.get("rollback_records") or []
                    updates["manager_verdicts"] = probe.get("manager_verdicts") or []
            if values.get("pending_scope_change"):
                from .recovery import consume_scope_confirmation

                probe = dict(values)
                if rejects_scope_change(code_feedback):
                    # 「重新生成/取消」→ 拒绝范围变更, 不清空重派反馈中的范围项。
                    probe.pop("pending_scope_change", None)
                    updates["pending_scope_change"] = None
                    logger.info("recovery_scope_change_rejected", feedback=code_feedback[:40])
                elif consume_scope_confirmation(probe):
                    updates["scope_change_approved"] = probe.get("scope_change_approved")
                    updates["pending_scope_change"] = None
            # 10.1: 已确认的范围变更 → checkpoint failure_details (code worker
            # 重跑即消费; 带去重守卫, 与 manager_gate redo 注入共存不重复)。
            if updates.get("scope_change_approved"):
                note = updates["scope_change_approved"]
                if isinstance(note, str) and note.strip():
                    fd = dict(probe.get("failure_details") or {})
                    instruction = fd.get("instruction", "")
                    block = f"[用户已确认的范围变更] {note.strip()}"
                    if block not in instruction:
                        fd["instruction"] = (instruction + "\n" if instruction else "") + block
                        fd.setdefault("source", "code")
                        fd.setdefault("failed_items", [])
                        fd.setdefault("rollback_target", "code")
                        updates["failure_details"] = fd
            if updates:
                self.app.update_state(config, updates)
                logger.info(
                    "recovery_resume_consumed",
                    escalated="escalated_signature" in updates,
                    scope="scope_change_approved" in updates,
                    scope_rejected=updates.get("pending_scope_change") is None
                    and "scope_change_approved" not in updates,
                )
        except Exception as e:
            logger.warning("recovery_resume_consume_failed", error=str(e))

        # Group 6 (review I3): sync the confirmation into the checkpoint ONLY
        # when the resume request explicitly carries it — never inferred from
        # the pause position alone.
        if e2e_confirmed:
            try:
                snap = self.app.get_state(config)
                pending = snap.next
                worker = pending[0] if isinstance(pending, (tuple, list)) else pending
                values = snap.values or {}
                if (
                    worker == "e2e"
                    and values.get("e2e_test_cases")
                    and not values.get("e2e_user_confirmed")
                ):
                    self.app.update_state(config, {"e2e_user_confirmed": True})
                    logger.info("e2e_confirmed_synced", generation_id=generation_id)
            except Exception as e:
                logger.warning("e2e_confirm_sync_failed", generation_id=generation_id, error=str(e))

        max_iterations = 50
        iteration = 0

        confirm_emitted = False
        async for event in self.app.astream(Command(resume=True), config):
            iteration += 1
            # capture the worker node being judged so the loop_break event
            # carries a real stage (the 求援 card needs it, task group 2.5)
            active_node = next((n for n in event if not n.startswith("__")), "")
            if iteration > max_iterations:
                yield self._make_event("loop_break", active_node, {
                    "reason": f"Exceeded max iterations ({max_iterations})",
                })
                break

            for node_name, node_output in event.items():
                # langgraph may yield control events (e.g. {'__interrupt__': ()})
                if node_name.startswith("__"):
                    continue
                # manager_gate: emit verdicts; no stage events (it is not a worker)
                if node_name == "manager_gate":
                    for v in self._manager_verdict_events(node_output):
                        yield v
                    continue

                # 7.4: run_context 随阶段切换更新 (写透到暂存区, fail-open)。
                from .memory import update_run_context
                update_run_context(node_output, stage=node_name, phase="generating", active_node=node_name)

                yield self._make_event("stage_start", node_name, {"phase": "generating"})

                # Don't pause for analysis in Phase 2 (PRD already shown, user clicked next)
                if node_name in ("code", "e2e"):
                    # Confirmed e2e pass-through hands over to the frontend
                    # runner — no second confirm prompt (group 6).
                    if not (node_name == "e2e" and node_output.get("e2e_user_confirmed")):
                        confirm_emitted = True
                        yield self._make_event("human_confirm_required", node_name, {
                            "message": f"Please review the {node_name} output and confirm to continue.",
                        })

                yield self._make_event("stage_complete", node_name, {
                    "summary": self._get_summary(node_name, node_output),
                })

                if node_name == "e2e":
                    for ev in self._e2e_node_events(node_output):
                        yield ev

        # If the gate paused at a worker without a pending confirmation, announce it.
        async for ev in self._announce_paused_worker(config, confirm_emitted):
            yield ev

    async def resume_after_e2e(
        self,
        generation_id: str,
        e2e_results: list[dict],
    ) -> AsyncIterator[dict]:
        """Resume graph with E2E results and continue execution.

        Group 6: failed cases first go through the Test Diagnoser (6.4) —
        expected_broken / selector_coupled failures do NOT trigger the code
        rollback (only real_regression cases do; skipped_requires_browser
        cases are never failures, 6.7). The diagnosis event + manager cards
        surface the classification to the user.
        """
        self._generation_id = generation_id
        config = {"configurable": {"thread_id": generation_id}}
        try:
            current_state = self.app.get_state(config)
        except Exception as e:
            logger.error("get_state_failed", error=str(e))
            yield self._make_event("error", "e2e", {
                "reason": f"Failed to retrieve state: {str(e)}",
            })
            return

        # ── Test Diagnoser (6.4): classify the failed cases ──
        diagnosis = None
        executed_failed = [
            r for r in e2e_results
            if not r.get("passed", False) and r.get("status") != "skipped_requires_browser"
        ]
        if executed_failed:
            from .e2e_designer import project_root_for
            from .e2e_diagnoser import diagnose_failures

            diagnosis = await diagnose_failures(
                current_state.values,
                e2e_results,
                project_root=project_root_for(current_state.values),
                llm_fn=self._llm_fn,
            )
            yield self._make_event("e2e_diagnosis", "e2e", diagnosis)
            # Only real regressions roll back to the code worker.
            rollback_ids = set(diagnosis.get("rollback_case_ids") or [])
            failed = [
                r for r in executed_failed if r.get("case_id") in rollback_ids
            ]
        else:
            failed = []

        passed = not failed

        # 8.5 回归对账 (增量模式): 按用例状态对账 — active 红 = 真回归,
        # expected_broken 红 = 预期, archived = 不执行; 结果写入 changes/ 记录。
        if (current_state.values or {}).get("incremental_mode") and (
            current_state.values or {}
        ).get("change_manifest"):
            try:
                from .e2e_designer import project_root_for
                from .incremental import (
                    build_regression_accounting,
                    record_regression_results,
                )

                values = current_state.values
                root = project_root_for(values)
                accounting = build_regression_accounting(
                    values, e2e_results, diagnosis,
                    values.get("test_dispositions") or [], root,
                )
                record_regression_results(
                    root,
                    values.get("change_id") or "",
                    values, e2e_results, diagnosis,
                    values.get("test_dispositions") or [], accounting,
                )
                yield self._make_event("e2e_regression_accounting", "e2e", accounting)
            except Exception as e:  # noqa: BLE001 — fail-open
                logger.warning("incremental_regression_accounting_failed", error=str(e))

        yield self._make_event("e2e_complete", "e2e", {
            "passed": passed,
            "failed_count": len(failed),
            "total_count": len(e2e_results),
            "diagnosis": diagnosis,
        })

        if not passed:
            failed_text = "\n".join(
                f"- {r.get('case_id', '?')}: {r.get('error', 'unknown error')}"
                for r in failed
            )
            # Apply loop control
            allowed, reason = self.loop_control.should_rollback("code", current_state.values)
            if not allowed:
                logger.warning("loop_break", reason=reason)
                # 9.4: 熔断转求援 — 带失败分类上下文 (no_convergence), 恢复
                # 事件/问题记录落库 (9.5); 求援卡由前端 loop_break 处理器合成
                # (继续自主/转人工)。「继续自主」resume → consume_escalation_reset。
                from .recovery import run_recovery

                recovery = await run_recovery(
                    current_state.values,
                    node="e2e", decision="rollback", reason=reason,
                    hint="loop_control_blocked", llm_fn=self._llm_fn,
                )
                signature = recovery["classification"]["signature"]
                yield self._make_event("loop_break", "e2e", {
                    "reason": reason,
                    "classification": recovery["classification"]["category"],
                    "strategy": recovery["strategy"]["strategy"],
                    "signature": signature,
                })
                # Force pass with manual review flag
                state_update = {
                    "e2e_results": e2e_results,
                    "e2e_passed": True,
                    "e2e_diagnosis": diagnosis,
                    # consumed by task group 9 (recovery ladder); the frontend
                    # banner was migrated to the dialog 求援 card (task group 2)
                    "needs_manual_review": True,
                    # 9.3 红线标记 + run_recovery 的 in-place 副作用 (checkpoint
                    # 只合并 state_update 的键, 其余突变不会持久化)。
                    "escalated_signature": signature,
                    "recovery_events": current_state.values.get("recovery_events") or [],
                    "problem_attempts": current_state.values.get("problem_attempts") or {},
                    "recovery_last": current_state.values.get("recovery_last"),
                }
                self.app.update_state(config, state_update)
                return

            state_update = {
                "e2e_results": e2e_results,
                "e2e_passed": False,
                "e2e_diagnosis": diagnosis,
                "failure_details": {
                    "source": "e2e",
                    "failed_items": failed,
                    "instruction": f"E2E 测试失败（真实回归），以下用例未通过：\n{failed_text}",
                    "rollback_target": "code",
                },
            }
        else:
            state_update = {
                "e2e_results": e2e_results,
                "e2e_passed": True,
                "e2e_diagnosis": diagnosis,
            }

        self.app.update_state(config, state_update)

        # Continue streaming from current state
        async for event in self.app.astream(None, config):
            for node_name, node_output in event.items():
                if node_name.startswith("__"):
                    continue
                if node_name == "manager_gate":
                    for v in self._manager_verdict_events(node_output):
                        yield v
                    continue
                if node_name == "e2e":
                    continue
                yield self._make_event("stage_start", node_name, {})
                yield self._make_event("stage_complete", node_name, {
                    "summary": self._get_summary(node_name, node_output),
                })

        # Group 6 (review I2): the continuation loop emits no confirm prompts
        # itself — announce the graph's pause so a rollback to the code worker
        # (real regression) hands the user a confirm/continue prompt instead
        # of stalling the UI. The announcement wording already handles
        # redo/rollback verdicts. On the pass path (→ END) there is no pending
        # worker and the announcement is a no-op.
        async for ev in self._announce_paused_worker(config, False):
            yield ev

    def _make_event(self, event_type: str, stage: str, data: dict) -> dict:
        """Build a GraphEvent dict and route it through trajectory archiving."""
        return self._track_event({"event_type": event_type, "stage": stage, "data": data})

    def _track_event(self, event: dict) -> dict:
        """Route an event dict through the mid-term trajectory archive (7.5).

        Every emitted event (including queue-drained phase-3 executor/planner
        events that bypass ``_make_event``) must pass through here so the
        archive captures curated types; streaming token chunks and other
        high-frequency events are filtered out. Fire-and-forget + fail-open —
        never blocks the stream.
        """
        if (
            event.get("event_type") in _TRAJECTORY_EVENT_TYPES
            and self._memory_db is not None
            and self._generation_id
        ):
            try:
                self._memory_db.append_trajectory(
                    self._generation_id,
                    event.get("event_type", ""),
                    event.get("stage", ""),
                    event.get("data") or {},
                )
            except Exception as e:  # pragma: no cover - fail-open
                logger.warning("trajectory_append_failed", error=str(e))
        return event

    def _persist_verdict(self, state: dict, node: str, decision: str, reason: str) -> None:
        """7.3 把关裁决 → decisions.md + index 阶段完成 + 裁决日志 + run_context
        (fail-open). index 持久化裁决 (M1): 崩溃恢复后 decisions.md 重写不丢历史。"""
        try:
            from .memory import (
                project_root_for,
                update_index,
                update_run_context,
                write_decisions,
            )

            root = project_root_for(state)
            write_decisions(root, state)
            update_run_context(
                state,
                stage=node,
                phase="reviewed",
                active_node="gate",
                latest_verdict={
                    "node": node,
                    "decision": decision,
                    "reason": (reason or "")[:200],
                },
            )
            verdicts = list(state.get("manager_verdicts") or [])
            if decision == "pass":
                update_index(root, stage=node, verdicts=verdicts)
            else:
                update_index(root, verdicts=verdicts)

            # 8.6 增量变更收尾: e2e 过关 → changes/ 记录定稿 + state.json 功能
            # 状态推进 + index.json 版本推进 (fail-open)。
            # 11.4 (review fix): 必须等执行结果回填 (e2e_results 非空) — 用例
            # 待确认阶段的 e2e pass 裁决 (results=None) 不得提前定稿/推进版本
            # (否则 change_revision 虚增、changes/ 记录在执行前即标 completed)。
            if (
                decision == "pass"
                and node == "e2e"
                and state.get("incremental_mode")
                and state.get("change_manifest")
                and state.get("e2e_results") is not None
            ):
                try:
                    from .incremental import finalize_incremental_change

                    finalize_incremental_change(
                        state,
                        root,
                        state.get("change_id") or "",
                        e2e_verdict=decision,
                        e2e_reason=reason,
                    )
                except Exception as _e:  # noqa: BLE001 — fail-open
                    logger.warning("incremental_finalize_failed", error=str(_e))
        except Exception as e:  # pragma: no cover - fail-open
            logger.warning("memory_verdict_persist_failed", error=str(e))

    def _persist_stage(self, state: dict, stage: str) -> None:
        """7.3 节点完成 → spec/state/contracts 落盘 (persist_stage_artifacts)."""
        try:
            from .memory import persist_stage_artifacts

            persist_stage_artifacts(state, stage)
        except Exception as e:  # pragma: no cover - fail-open
            logger.warning("memory_stage_persist_failed", stage=stage, error=str(e))

    def _record_problem(
        self,
        state: dict,
        *,
        category: str,
        problem: str,
        root_cause: str = "",
        fix: str = "",
        result: str = "",
    ) -> None:
        """7.3 问题留痕 → problems.jsonl + 中期/长期记忆 (fail-open)."""
        try:
            from .memory import record_problem

            record_problem(
                state,
                category=category,
                problem=problem,
                root_cause=root_cause,
                fix=fix,
                result=result,
            )
        except Exception as e:  # pragma: no cover - fail-open
            logger.warning("memory_problem_record_failed", error=str(e))

    async def _run_incremental_entry(
        self,
        state: GenerationState,
        generation_id: str,
    ) -> AsyncIterator[dict]:
        """8.1-8.4 增量开发入口 — 逐级确认 (每级产事件后由 run() 停等 resume).

        State-driven idempotence (resume 后 run() 重新进入, 已确认的级跳过):
        - Step A (无 ``incremental_diff``): 加载应用记忆 → 功能点 diff → 卡片确认;
        - Step B (无 ``change_manifest``): 生成变更 manifest → 草稿记录 → 卡片确认;
        - Step C (无 ``test_dispositions``): Test Impact 处置清单 → 卡片确认;
        - Step D (全部已确认): 应用处置 (retire→archived, update→expected_broken),
          不产事件 → run() 落回增量流水线 (增量 PRD → 增量设计 → delta 实现)。
        """
        from .memory import project_root_for
        from .incremental import (
            analyze_test_impact,
            apply_dispositions,
            build_change_id,
            classify_diff,
            generate_manifest,
            load_existing_cases,
            load_incremental_context,
            write_change_record,
        )
        from .dialog import (
            render_diff_card,
            render_disposition_card,
            render_existing_summary,
            render_manifest_card,
            summary_card_event,
        )

        project_root = project_root_for(state)

        # ── Step A: diff (8.1) ──
        if not state.get("incremental_diff"):
            logger.info("incremental_entry_diff gen=%s", generation_id)
            context = load_incremental_context(project_root)
            state["incremental_context"] = context
            diff = await classify_diff(
                context.get("features") or [],
                state.get("requirement", ""),
                llm_fn=self._llm_fn,
            )
            state["incremental_diff"] = diff
            yield self._make_event("stage_start", "analysis", {"phase": "incremental"})
            yield summary_card_event("analysis", render_existing_summary(context))
            yield _incremental_confirm_card("analysis", render_diff_card(diff))
            yield self._make_event("human_confirm_required", "analysis", {
                "message": "请确认增量变更清单（diff）。",
            })
            return

        # ── Step B: manifest (8.2) ──
        if not state.get("change_manifest"):
            logger.info("incremental_entry_manifest gen=%s", generation_id)
            manifest = await generate_manifest(
                state,
                state.get("incremental_diff"),
                llm_fn=self._llm_fn,
            )
            state["change_manifest"] = manifest
            change_id = manifest.get("change_id") or build_change_id(project_root)
            state["change_id"] = change_id
            write_change_record(project_root, change_id, {
                "status": "draft",
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "diff": state.get("incremental_diff"),
                "manifest": manifest,
            })
            yield _incremental_confirm_card("analysis", render_manifest_card(manifest))
            yield self._make_event("human_confirm_required", "analysis", {
                "message": "请确认变更 manifest。",
            })
            return

        # ── Step C: test dispositions 草稿 (8.4) ──
        if state.get("test_dispositions") is None:
            # review C1: 用 is-None 判定 —— 计算出的空清单 [] 也是有效结果,
            # 不得用 truthiness 误判为"未计算" (否则无历史用例时死循环)。
            if state.get("incremental_dispositions") is None:
                logger.info("incremental_entry_dispositions gen=%s", generation_id)
                existing_cases = (
                    (state.get("incremental_context") or {}).get("e2e_cases")
                    or load_existing_cases(project_root)
                )
                dispositions = analyze_test_impact(
                    state.get("change_manifest"),
                    existing_cases,
                    diff=state.get("incremental_diff"),
                )
                state["incremental_dispositions"] = dispositions
                yield _incremental_confirm_card("e2e", render_disposition_card(dispositions))
                yield self._make_event("human_confirm_required", "e2e", {
                    "message": "请确认历史用例处置清单。",
                })
                return
            # ── Step D: 用户已确认 → 草稿转正并应用 (无事件 → 落入增量流水线) ──
            logger.info("incremental_entry_apply_dispositions gen=%s", generation_id)
            state["test_dispositions"] = list(state.get("incremental_dispositions") or [])
            state["incremental_dispositions"] = None
            apply_dispositions(project_root, state.get("test_dispositions"))

    def regen_incremental_step(self) -> None:
        """8.x (review I1): 增量确认卡「重新生成」— 清除当前待确认级的产物,
        下一次 resume 后 run() 从该级重新计算 (diff/manifest/处置均可重跑)。"""
        state = self._state
        if not state or not state.get("incremental_mode"):
            return
        if state.get("incremental_dispositions") is not None:
            state["incremental_dispositions"] = None
            logger.info("incremental_regen_step", step="dispositions")
        elif state.get("change_manifest"):
            state["change_manifest"] = None
            state["change_id"] = None
            logger.info("incremental_regen_step", step="manifest")
        elif state.get("incremental_diff"):
            state["incremental_diff"] = None
            logger.info("incremental_regen_step", step="diff")

    def _rescue_card(self, stage: str, recovery: dict, evidence=None) -> dict:
        """9.3 求援卡: 红线/熔断后替代普通诊断卡 — 携带 [继续自主, 转人工] 选项
        (frontend ChatPanel 已按选项分流: 继续自主 → confirmStage/resume,
        转人工 → manualMode)。"""
        from .dialog import diagnosis_card_event
        from .recovery import RESCUE_OPTIONS, STRATEGY_LABELS

        attempts = recovery.get("attempts", 1)
        strategy = recovery.get("strategy") or {}
        suggestion = (
            f"已自主处理 {attempts} 轮仍未通过（恢复策略："
            f"{STRATEGY_LABELS.get(strategy.get('strategy', ''), '未知')}）。"
            "请选择：继续自主（重置本轮计数后重试）或转人工接管。"
        )
        if recovery.get("suggested_fix"):
            suggestion += f"\n历史修复策略参考：{recovery['suggested_fix']}"
        return diagnosis_card_event(
            stage,
            evidence if evidence is not None else (recovery.get("reason") or "未提供诊断细节"),
            suggestion=suggestion,
            options=list(RESCUE_OPTIONS),
        )

    def _scope_confirm_card(self, stage: str, recovery: dict) -> dict:
        """9.3 范围变更红线: 诊断建议删减/修改需求范围 → confirm_card,
        未经用户确认 Manager 不得自行执行 (resume 后获批进入重派反馈)。"""
        from .dialog import confirm_card_event
        from .recovery import SCOPE_OPTIONS

        note = recovery.get("scope_change_note") or ""
        event = confirm_card_event(
            stage,
            f"诊断建议修改需求范围（Manager 不得自行删减，需你确认）：\n{note}",
            options=list(SCOPE_OPTIONS),
        )
        # I5: 范围确认卡标记 — 前端据此把「确认」路由到 resume (批准范围变更),
        # 「重新生成」路由到 feedback (拒绝)。与增量确认卡的 incremental 标记
        # 互斥 (数据面不同分支)。
        event["data"] = {**event.get("data", {}), "scope_confirm": True}
        return event

    async def _gate_manual_stage(
        self,
        state: GenerationState,
        stage: str,
        llm_fn: Any | None = None,
    ) -> list[dict]:
        """Run the manager gate (L1 + design L2) for a manually-completed stage.

        Appends the verdict to state and returns the ``manager_verdict`` event
        followed by the Manager speech cards (task 2.4): summary_card +
        verdict_card on pass, diagnosis_card on fail. On design L2 failure the
        diagnosis carries the missing list; on L1 failure the L1 evidence.

        Task group 9: on redo/rollback the failure is classified and routed
        through the recovery ladder (9.1-9.2); red-line escalation (9.3) emits
        a 求援 diagnosis_card with [继续自主, 转人工] instead of the plain
        diagnosis card; a scope-change proposal emits a confirm_card that must
        be confirmed before any re-run (9.3). Gate redo/rollback also routes
        through LoopControl (9.4) — per-node/global/no-improvement limits.
        """
        fn = llm_fn if llm_fn is not None else self._llm_fn
        decision, reason, evidence, missing = await evaluate_stage_l2(state, stage, fn)
        recovery = None
        verdict_reason = reason
        if decision in ("redo", "rollback"):
            from .recovery import (
                build_recovery_feedback,
                gate_loop_check,
                run_recovery,
            )

            recovery = await run_recovery(
                state, node=stage, decision=decision, reason=reason,
                missing=missing, llm_fn=fn,
            )
            if not recovery["escalate"]:
                # 9.2 形式化: 分类理由 + 历史策略随重派反馈进入下一轮生成
                # (design_gate_feedback 消费 → 阶段 2 重跑 prompt)。
                verdict_reason = reason + "\n" + build_recovery_feedback(
                    recovery["classification"], recovery["strategy"]
                )
        record_verdict(state, stage, decision, verdict_reason)
        if recovery is not None:
            state["manager_verdicts"][-1]["recovery"] = {
                "category": recovery["classification"]["category"],
                "reason": recovery["classification"]["reason"],
                "strategy": recovery["strategy"],
                "attempts": recovery["attempts"],
                "escalate": recovery["escalate"],
                "scope_change": bool(recovery["classification"].get("scope_change")),
                "scope_change_note": recovery["classification"].get("scope_change_note", ""),
                "suggested_fix": recovery["classification"].get("suggested_fix", ""),
                "signature": recovery["classification"]["signature"],
            }
        elif decision == "pass":
            # 9.5: gate 通过 → 该节点未决恢复事件闭环 (resolved / stale)。
            from .recovery import resolve_recovery_outcomes

            resolve_recovery_outcomes(state, stage)
        # 9.4: 手动阶段把关 redo/rollback 同样过 LoopControl — 阶段重跑计数
        # (analysis 无重跑动作 → 不计数)。裁决先落盘, gate_loop_check 熔断时
        # 才能翻转当前裁决的 recovery.escalate (I2)。
        if decision in ("redo", "rollback") and recovery is not None:
            from .recovery import gate_loop_check

            target = {"design": "design", "code": "code"}.get(stage)
            escalated, state = gate_loop_check(state, stage, recovery, target=target)
            if escalated:
                state["needs_manual_review"] = True
        self._verdicts_emitted += 1
        # 7.3 write-through: gate verdicts → decisions.md + index + run_context;
        # stage completion → spec/state/contracts (fail-open, never blocks).
        self._persist_verdict(state, stage, decision, verdict_reason)
        if stage in ("analysis", "design", "code"):
            self._persist_stage(state, stage)
        missing_data = missing if (stage == "design" and decision != "pass") else []
        events = [self._make_event("manager_verdict", stage, {
            "node": stage,
            "decision": decision,
            "reason": verdict_reason,
            "missing": missing_data,
        })]
        if decision == "pass":
            events.extend(gate_speech_events(
                stage, decision, verdict_reason,
                summary=self._get_summary(stage, state),
                evidence=[],
                missing=[],
            ))
        else:
            rec = state["manager_verdicts"][-1].get("recovery") or {}
            if rec.get("escalate"):
                # 9.3 红线求援卡 — 替换普通诊断卡, 携带 继续自主/转人工 选项。
                events.append(self._rescue_card(stage, rec, evidence))
            else:
                events.extend(gate_speech_events(
                    stage, decision, verdict_reason,
                    summary=self._get_summary(stage, state),
                    evidence=evidence if decision != "pass" else [],
                    missing=missing_data,
                ))
            if rec.get("scope_change") and not rec.get("escalate"):
                events.append(self._scope_confirm_card(stage, rec))
                state["pending_scope_change"] = {
                    "note": rec.get("scope_change_note", ""),
                    "node": stage,
                    "signature": rec.get("signature", ""),
                }
        return events

    def _manager_verdict_events(self, output: dict) -> list[dict]:
        """Extract gate verdicts appended to graph state since the last emission.

        Each new verdict is followed by its Manager speech cards, mirroring
        ``_gate_manual_stage`` (task 2.4). Reused (deduped) verdicts produce no
        events, matching the pre-card behavior.
        """
        verdicts = output.get("manager_verdicts") or []
        events = []
        for verdict in verdicts[self._verdicts_emitted:]:
            node = verdict.get("node") or "manager"
            decision = verdict.get("decision", "pass")
            reason = verdict.get("reason", "")
            # 7.3 write-through: LangGraph-phase gate verdicts → decisions.md
            # + index stage-done + run_context (fail-open)。
            self._persist_verdict(output, node, decision, reason)
            # M2: phase-4 把关后同样刷新 state/contracts (code 阶段经
            # LangGraph worker 重跑时 state.json 与 gate 裁决保持一致)。
            if node in ("analysis", "design", "code"):
                self._persist_stage(output, node)
            events.append(self._make_event("manager_verdict", node, {
                "node": node,
                "decision": decision,
                "reason": reason,
            }))
            recovery = verdict.get("recovery") or {}
            if decision != "pass":
                if recovery.get("escalate"):
                    # 9.3 红线求援卡 — 替代普通诊断卡。
                    events.append(self._rescue_card(node, recovery))
                else:
                    evidence = run_l1_checks(output, node)
                    events.extend(gate_speech_events(
                        node, decision, reason,
                        summary=self._get_summary(node, output),
                        evidence=evidence,
                    ))
                if recovery.get("scope_change") and not recovery.get("escalate"):
                    events.append(self._scope_confirm_card(node, recovery))
                    output["pending_scope_change"] = {
                        "note": recovery.get("scope_change_note", ""),
                        "node": node,
                        "signature": recovery.get("signature", ""),
                    }
            else:
                events.extend(gate_speech_events(
                    node, decision, reason,
                    summary=self._get_summary(node, output),
                    evidence=[],
                ))
        self._verdicts_emitted = len(verdicts)
        return events

    async def _announce_paused_worker(self, config: dict, confirm_emitted: bool) -> AsyncIterator[dict]:
        """Announce a graph pause at a worker that has no pending confirmation.

        The gate routes between workers, so a pause can land on a worker that
        has not produced output in this stream — emit stage_start +
        human_confirm_required so the frontend can drive the next step
        (mirrors the old worker-run confirm cadence). The wording follows the
        last gate verdict (pass vs redo/rollback).
        """
        if confirm_emitted:
            return
        try:
            snapshot = self.app.get_state(config)
        except Exception as e:
            logger.error("get_state_failed_announce", error=str(e))
            return
        pending = snapshot.next
        if not pending:
            return
        worker = pending[0] if isinstance(pending, (tuple, list)) else pending
        if worker not in ("code", "e2e"):
            return
        if worker == "e2e":
            values = snapshot.values or {}
            if values.get("e2e_user_confirmed") and values.get("e2e_results") is None:
                # Confirmed pass-through (group 6): the frontend runner drives
                # execution from e2e_execute_start — no confirm prompt here.
                return

        values = snapshot.values or {}
        verdicts = values.get("manager_verdicts") or []
        last_verdict = verdicts[-1] if verdicts else {}
        # 9.3 红线: 熔断标记存在 → 求援卡 (继续自主/转人工) 替代普通确认 —
        # gate 停在 worker 中断处, 不自主派发; 「继续自主」resume 时由
        # consume_escalation_reset 重置计数后继续。
        # I1: 裁决路径 (_manager_verdict_events) 已发射求援卡时不再重复 —
        # 裁决 recovery.escalate=True 意味着卡面已随裁决流出, 这里只补
        # 普通确认让流程可继续; 熔断标记来自无裁决路径 (如 e2e loop_break
        # 之外的外部标记) 时才在这里发射求援卡。
        if values.get("escalated_signature"):
            recovery = last_verdict.get("recovery") or {}
            if recovery.get("escalate"):
                message = f"Manager 判定 {worker} 未通过（需返工），确认后重新执行。"
                yield self._make_event("stage_start", worker, {})
                yield self._make_event("human_confirm_required", worker, {
                    "message": message,
                })
            else:
                yield self._make_event("stage_start", worker, {})
                yield self._rescue_card(worker, recovery)
            return
        if last_verdict.get("decision") in ("redo", "rollback"):
            judged = last_verdict.get("node") or worker
            message = f"Manager 判定 {judged} 未通过（需返工），确认后重新执行。"
        else:
            message = f"Manager 把关通过，确认继续 {worker} 阶段。"

        yield self._make_event("stage_start", worker, {})
        yield self._make_event("human_confirm_required", worker, {
            "message": message,
        })

    @staticmethod
    def _get_summary(node_name: str, output: dict) -> str:
        summaries = {
            "analysis": (output.get("analysis_result") or "")[:200],
            "design": (output.get("design_result") or "")[:200],
            "code": f"Generated {len(output.get('code_result') or '')} chars of code",
            "e2e": f"E2E: {'pass' if output.get('e2e_passed') else 'fail'}",
        }
        return summaries.get(node_name, "")
