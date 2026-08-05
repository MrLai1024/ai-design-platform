"""gRPC GenerationService implementation — powered by LangGraph."""

import json
import logging
from typing import AsyncIterator

import grpc
from ai.v1.generation_pb2 import (
    BrainstormTurnRequest,
    BrainstormTurnResponse,
    CancelRequest,
    CancelResponse,
    ClassifyIntentRequest,
    ClassifyIntentResponse,
    CompileFeedbackRequest,
    CompileFeedbackResponse,
    GenerateRequest,
    GenerateResponse,
    GenerationComplete,
    GenerationError,
    RuntimeFeedbackRequest,
    RuntimeFeedbackResponse,
    ResumeAfterE2ERequest,
    Token,
    ToolCall as ProtoToolCall,
    Usage as ProtoUsage,
    GraphEvent as ProtoGraphEvent,
)
from ai.v1.generation_pb2_grpc import GenerationServiceServicer

from app.services.llm.provider import (
    CompleteEvent,
    LLMConfig,
    Message,
    ReasoningEvent,
    TokenEvent,
    ToolCallEvent,
)
from app.services.llm.router import resolve_provider
from .graph import GraphRunner
from .nodes import set_provider
from .state import GenerationState

logger = logging.getLogger(__name__)


class GenerationServicer(GenerationServiceServicer):
    """gRPC service for LLM generation — supports both direct chat and LangGraph pipeline."""

    def __init__(self) -> None:
        self._active_generations: dict[str, str] = {}  # generation_id -> "running"|"cancelling"
        self._active_runners: dict[str, GraphRunner] = {}

    async def StreamGenerate(
        self,
        request: GenerateRequest,
        context: grpc.aio.ServicerContext,
    ) -> AsyncIterator[GenerateResponse]:
        """Server-streaming RPC: stream tokens or LangGraph events to the caller."""
        generation_id = request.generation_id
        model = request.model or "glm-5.2"
        mode = request.metadata.get("mode", "chat")  # "chat" or "graph"

        if mode == "graph":
            async for response in self._stream_graph(generation_id, request, context):
                yield response
        else:
            async for response in self._stream_chat(generation_id, model, request, context):
                yield response

    async def _stream_graph(
        self,
        generation_id: str,
        request: GenerateRequest,
        context: grpc.aio.ServicerContext,
    ) -> AsyncIterator[GenerateResponse]:
        """Stream LangGraph pipeline events. Auto-detects resume vs fresh start."""
        self._active_generations[generation_id] = "running"
        model = request.model or "glm-5.2"
        mode = request.metadata.get("mode", "graph")

        # Set up LLM provider for the graph nodes
        provider = resolve_provider(model)
        set_provider(provider)

        # Check if this is a resume (existing runner has state)
        existing_runner = self._active_runners.get(generation_id)

        if mode == "resume" and existing_runner:
            # Resume from checkpoint
            runner = existing_runner
            # 8.x (review I1): 增量确认卡「重新生成」— 清除当前待确认级产物,
            # resume 后从该级重新计算。
            if request.metadata.get("regen") == "true":
                runner.regen_incremental_step()
            # Group 6 (review I3): explicit E2E-case confirmation — only the
            # E2EStagePanel 确认按钮 path sends this flag; chat-intent
            # proceed resumes without it, so cases are never auto-confirmed.
            e2e_confirmed = request.metadata.get("e2e_confirmed") == "true"
            # 9.3: gateway 注入的待处理反馈文本 — 范围确认卡「重新生成/取消」
            # 视为拒绝范围变更 (resume 消费)。
            code_feedback = request.metadata.get("code_feedback", "")
            try:
                async for event in runner.resume(
                    generation_id, e2e_confirmed=e2e_confirmed, code_feedback=code_feedback
                ):
                    if context.cancelled() or self._active_generations.get(generation_id) == "cancelling":
                        break
                    yield self._event_to_response(event)

                yield GenerateResponse(
                    complete=GenerationComplete(finish_reason="stop", usage=None)
                )
            except Exception as e:
                logger.exception("Graph resume failed: generation_id=%s", generation_id)
                yield GenerateResponse(
                    error=GenerationError(code="INTERNAL", message=str(e))
                )
            return

        # Check if we should skip analysis (PRD already generated via /api/v1/prd/stream)
        skip_analysis = request.metadata.get("skip_analysis") == "true"
        code_feedback = request.metadata.get("code_feedback", "")
        # 8.1 增量开发入口: 用户对已有应用 (同 generation_id 的 .ai-memory) 提出
        # 新需求 → 加载记忆 → diff → manifest → 用例处置 → 增量流水线。
        incremental = request.metadata.get("incremental") == "true"

        # Fresh start — build initial state
        user_messages = []
        user_content = ""
        for m in request.messages:
            try:
                role, content = m.role, m.content
            except AttributeError:
                role = m.get("role", "")
                content = m.get("content", "")
            user_messages.append({"role": str(role), "content": str(content)})
            if str(role) == "user" and not user_content:
                user_content = str(content)

        # If skip_analysis, pre-fill completed stages
        pre_filled_analysis = user_content if skip_analysis else None
        # Second message (assistant role) = pre-filled design_result
        pre_filled_design = None
        pre_filled_code = None
        if skip_analysis:
            if len(user_messages) >= 2 and user_messages[1].get("role") == "assistant":
                pre_filled_design = user_messages[1].get("content")
            if len(user_messages) >= 3 and user_messages[2].get("role") == "assistant":
                pre_filled_code = user_messages[2].get("content")

        # Task group 3: load the brainstorm session products (structured
        # requirement + decisions + assumptions) when this generation_id maps
        # to a converged BrainstormSession. Lazy-compute if the session
        # converged without products (defensive; provider is set above).
        from .brainstorm import get_session as get_brainstorm_session
        from .brainstorm import to_requirements_state_json as session_to_requirements

        session = get_brainstorm_session(request.generation_id)
        requirements_state_json: str | None = None
        brainstorm_decisions: list | None = None
        brainstorm_assumptions: list | None = None
        if session is not None:
            if session.converged and session.requirements_state_json is None:
                session.requirements_state_json = await session_to_requirements(session)
            if session.requirements_state_json:
                requirements_state_json = session.requirements_state_json
                brainstorm_decisions = list(session.decisions)
                brainstorm_assumptions = list(session.assumptions)
                logger.info(
                    "brainstorm_session_loaded gen=%s items=%d decisions=%d assumptions=%d",
                    request.generation_id, len(session.agenda),
                    len(brainstorm_decisions), len(brainstorm_assumptions),
                )
            else:
                from .brainstorm import coverage as brainstorm_coverage

                logger.warning(
                    "brainstorm_session_not_converged gen=%s converged=%s coverage=%.2f",
                    request.generation_id, session.converged,
                    brainstorm_coverage(session),
                )

        logger.info(
            "stream_graph_state_init gen=%s skip_analysis=%s mode=%s has_analysis=%s analysis_len=%d has_design=%s design_len=%d has_code=%s",
            generation_id, skip_analysis, mode, bool(pre_filled_analysis),
            len(pre_filled_analysis or ""), bool(pre_filled_design),
            len(pre_filled_design or ""), bool(pre_filled_code),
        )

        user_id = request.metadata.get("user_id", "default")

        state: GenerationState = {
            "requirement": user_content,
            "component_lib": "",
            "messages": user_messages,
            "generation_id": generation_id,
            "user_id": user_id,
            "requirements_state_json": requirements_state_json,
            "brainstorm_decisions": brainstorm_decisions,
            "brainstorm_assumptions": brainstorm_assumptions,
            "analysis_result": pre_filled_analysis,
            "design_result": pre_filled_design,
            "code_result": pre_filled_code,
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
            # New fields
            "stage_phase": "generating",
            "design_doc": None,
            # Architecture Spec (D5) — the design node's machine-readable
            # product (4.2); the Manager's gating object (4.3 L1 / 4.4 L2).
            "architecture_spec": None,
            "generated_files": {},
            "compile_errors": None,
            "e2e_test_cases_md": None,
            "e2e_user_confirmed": False,
            # Manager-worker orchestration (base dispatch contract; per-phase
            # contracts are refined in later task groups)
            "dispatch_contract": {
                "task_id": "analysis",
                "input_ref": "requirement",
                "acceptance_criteria": ["PRD 非空且含功能模块与页面结构"],
                "tool_bounds": [],
                "constraints": [],
            },
            "manager_verdicts": [],
            "code_feedback": code_feedback,
            # 8.1 增量开发模式 (metadata incremental=true + 已有 .ai-memory):
            # graph 入口运行 diff → manifest → 用例处置的确认流。
            "incremental_mode": incremental,
        }

        # 7.6 长期用户级记忆 (graph start): 用户偏好 → 分发约束 (spec 场景:
        # 历史偏好的常用组件库作为约束写入分发与澄清上下文)。
        try:
            from .memory_db import get_memory_db

            prefs = get_memory_db().get_preferences(user_id)
            if prefs:
                constraints = list(state["dispatch_contract"].get("constraints") or [])
                constraints.extend(
                    f"用户偏好（长期记忆）：{k}={v}"
                    for k, v in prefs.items()
                )
                state["dispatch_contract"] = {
                    **state["dispatch_contract"],
                    "constraints": constraints,
                }
                logger.info(
                    "user_preferences_injected gen=%s user=%s keys=%d",
                    generation_id, user_id, len(prefs),
                )
        except Exception as e:
            logger.warning("preferences_load_failed gen=%s", generation_id, exc_info=e)

        # 7.7 崩溃恢复: 已有 .ai-memory 产物的同一 generation 重建已完成阶段
        # (已完成跳过; 进行中阶段由 phase-skip 逻辑重跑)。skip_analysis 为
        # 用户显式全量重来 — 不叠加恢复。增量模式不叠加恢复 — 增量流水线需要
        # 重跑 analysis/design/code (delta 框定), 已有产物由增量入口
        # (load_incremental_context) 单独装载。
        restored = False
        if not skip_analysis and not incremental:
            try:
                from .memory import load_app_state, project_root_for

                project_root = project_root_for(state)
                patch = load_app_state(project_root, generation_id)
                if patch:
                    state.update(patch)
                    restored = True
                    logger.info(
                        "memory_state_restored gen=%s patch_keys=%s",
                        generation_id, sorted(patch.keys()),
                    )
            except Exception as e:
                logger.warning("memory_restore_failed gen=%s", generation_id, exc_info=e)

        # 7.4 短期记忆初始化 + 7.2 应用记忆目录/清单落地 (spec 场景: 初始化后
        # .ai-memory/ 与 index.json 即存在)。
        try:
            from .memory import init_app_memory
            from .brainstorm import get_session as _get_session

            session = _get_session(generation_id)
            agenda_brief = [
                {
                    "id": a.get("id", ""),
                    "topic": a.get("topic", ""),
                    "status": a.get("status", ""),
                }
                for a in (session.agenda if session else [])
            ]
            # I3: 未恢复 (全新生成 / skip_analysis 全量重来) 时清空旧 index 的
            # 阶段完成标记 — 防止本次运行崩溃后, 下次恢复误读上一轮的状态。
            # 增量模式保留旧 index (阶段标记/裁决历史是已有应用的记忆本体)。
            init_app_memory(state, reset=(not restored) and not incremental)
            from .memory import update_run_context

            # 崩溃恢复已带 run_context (暂存区) 时保留其 stage (进行中续跑线索);
            # 全新生成则从 analysis 起步。
            ctx_updates: dict = {"phase": "generating", "active_node": "analysis", "agenda": agenda_brief}
            if not (state.get("run_context") or {}).get("stage"):
                ctx_updates["stage"] = "analysis"
            update_run_context(state, **ctx_updates)
        except Exception as e:
            logger.warning("memory_init_failed gen=%s", generation_id, exc_info=e)

        from .memory_db import get_memory_db

        runner = GraphRunner(memory_db=get_memory_db())
        self._active_runners[generation_id] = runner

        try:
            async for event in runner.run(state, generation_id):
                if context.cancelled() or self._active_generations.get(generation_id) == "cancelling":
                    break
                yield self._event_to_response(event)

            yield GenerateResponse(
                complete=GenerationComplete(
                    finish_reason="stop",
                    usage=None,
                )
            )

        except Exception as e:
            logger.exception("Graph generation failed: generation_id=%s", generation_id)
            yield GenerateResponse(
                error=GenerationError(code="INTERNAL", message=str(e))
            )
        finally:
            # Only clean up if graph completed (not interrupted)
            if context.cancelled():
                self._active_generations.pop(generation_id, None)
                self._active_runners.pop(generation_id, None)

    async def _stream_chat(
        self,
        generation_id: str,
        model: str,
        request: GenerateRequest,
        context: grpc.aio.ServicerContext,
    ) -> AsyncIterator[GenerateResponse]:
        """Stream direct LLM chat (backward compatible with existing /api/v1/chat/stream)."""
        self._active_generations[generation_id] = "running"

        provider = resolve_provider(model)

        messages = [
            Message(role=m.role, content=m.content)
            for m in request.messages
        ]

        # Support enable_thinking from both config and metadata
        enable_thinking = (
            request.config.enable_thinking
            or request.metadata.get("enable_thinking") == "true"
        )
        config = LLMConfig(
            temperature=request.config.temperature if request.config.temperature else 0.7,
            max_tokens=request.config.max_tokens if request.config.max_tokens else 4096,
            top_p=request.config.top_p if request.config.top_p else 1.0,
            stop_sequences=list(request.config.stop_sequences),
            enable_thinking=enable_thinking,
        )

        try:
            async for event in provider.stream_generate(model=model, messages=messages, config=config):
                if context.cancelled() or self._active_generations.get(generation_id) == "cancelling":
                    await provider.cancel()
                    yield GenerateResponse(
                        complete=GenerationComplete(finish_reason="cancelled", usage=None)
                    )
                    return

                if isinstance(event, TokenEvent):
                    yield GenerateResponse(token=Token(text=event.text, index=event.index))
                elif isinstance(event, ReasoningEvent):
                    yield GenerateResponse(
                        token=Token(reasoning_content=event.text, index=event.index)
                    )
                elif isinstance(event, ToolCallEvent):
                    yield GenerateResponse(
                        tool_call=ProtoToolCall(
                            id=event.call_id, name=event.name, arguments=event.arguments
                        )
                    )
                elif isinstance(event, CompleteEvent):
                    yield GenerateResponse(
                        complete=GenerationComplete(
                            finish_reason=event.finish_reason,
                            usage=ProtoUsage(
                                prompt_tokens=event.usage.get("prompt_tokens", 0),
                                completion_tokens=event.usage.get("completion_tokens", 0),
                                total_tokens=event.usage.get("total_tokens", 0),
                            ) if event.usage else None,
                        )
                    )
        except Exception as e:
            logger.exception("Chat generation failed: generation_id=%s model=%s", generation_id, model)
            yield GenerateResponse(
                error=GenerationError(code="INTERNAL", message=str(e))
            )
        finally:
            self._active_generations.pop(generation_id, None)

    async def CancelGeneration(
        self,
        request: CancelRequest,
        context: grpc.aio.ServicerContext,
    ) -> CancelResponse:
        """Cancel an in-progress generation."""
        gid = request.generation_id
        if gid in self._active_generations:
            self._active_generations[gid] = "cancelling"
            return CancelResponse(success=True)
        return CancelResponse(success=False)

    async def ReportCompileFeedback(
        self,
        request: CompileFeedbackRequest,
        context: grpc.aio.ServicerContext,
    ) -> CompileFeedbackResponse:
        """Receive real bundler compile results from the frontend preview."""
        gid = request.generation_id
        runner = self._active_runners.get(gid)
        if runner is None:
            logger.warning("compile_feedback_no_runner gen=%s", gid)
            return CompileFeedbackResponse(received=False)

        errors = [
            {"file": e.file, "line": e.line, "column": e.column, "text": e.text}
            for e in request.errors
        ]
        consumed = runner.report_compile_feedback(request.ok, errors)
        logger.info(
            "compile_feedback gen=%s ok=%s errors=%d consumed=%s",
            gid, request.ok, len(errors), consumed,
        )
        return CompileFeedbackResponse(received=True)

    async def ReportRuntimeFeedback(
        self,
        request: RuntimeFeedbackRequest,
        context: grpc.aio.ServicerContext,
    ) -> RuntimeFeedbackResponse:
        """Receive preview-iframe runtime errors (Verifier L3 / Debugger evidence)."""
        gid = request.generation_id
        runner = self._active_runners.get(gid)
        if runner is None:
            logger.warning("runtime_feedback_no_runner gen=%s", gid)
            return RuntimeFeedbackResponse(received=False)

        errors = [
            {"type": e.type, "message": e.message, "stack": e.stack, "url": e.url}
            for e in request.errors
        ]
        consumed = runner.report_runtime_errors(errors)
        logger.info(
            "runtime_feedback gen=%s errors=%d consumed=%s",
            gid, len(errors), consumed,
        )
        return RuntimeFeedbackResponse(received=True)

    async def ResumeAfterE2E(
        self,
        request: ResumeAfterE2ERequest,
        context: grpc.aio.ServicerContext,
    ) -> AsyncIterator[GenerateResponse]:
        """Resume the graph with the completed E2E run results (task group 6).

        The runner POSTs the full batch; the Test Diagnoser classifies failed
        cases (3-way, 6.4), the gate routes real regressions back to the code
        worker, and the stream carries manager verdicts / diagnosis cards.
        """
        gid = request.generation_id
        runner = self._active_runners.get(gid)
        if runner is None:
            logger.warning("resume_after_e2e_no_runner gen=%s", gid)
            yield GenerateResponse(
                error=GenerationError(code="NOT_FOUND", message="No active runner for this generation")
            )
            return

        results = [
            {
                "case_id": r.case_id,
                "passed": r.passed,
                "error": r.error,
                "status": r.status,
                "screenshot": r.screenshot,
                "evidence": {
                    "dom_snapshot": (r.evidence.dom_snapshot if r.evidence else "") or "",
                    "console_errors": list(r.evidence.console_errors) if r.evidence else [],
                    "network_errors": list(r.evidence.network_errors) if r.evidence else [],
                    "screenshot_note": (r.evidence.screenshot_note if r.evidence else "") or "",
                },
            }
            for r in request.results
        ]
        logger.info(
            "resume_after_e2e gen=%s results=%d",
            gid, len(results),
        )
        try:
            async for event in runner.resume_after_e2e(gid, results):
                if context.cancelled():
                    break
                yield self._event_to_response(event)
        except Exception as e:
            logger.exception("resume_after_e2e_failed gen=%s", gid)
            yield GenerateResponse(
                error=GenerationError(code="INTERNAL", message=str(e))
            )

    async def ClassifyIntent(
        self,
        request: ClassifyIntentRequest,
        context: grpc.aio.ServicerContext,
    ) -> ClassifyIntentResponse:
        """Classify the user's dialog input for Manager intent routing (task 2.3).

        One lightweight LLM call; the Manager resolves the intent so the
        frontend has no routing rules of its own. The provider instance is
        threaded into ``classify_intent`` directly — the shared ``_provider``
        singleton is deliberately NOT touched here, so a classify call running
        concurrently with a graph stream cannot swap the provider mid-stream.
        """
        from .dialog import classify_intent

        try:
            provider = resolve_provider("glm-5.2")
            result = await classify_intent(
                request.text, request.stage, request.generation_id,
                provider=provider,
            )
        except Exception as e:
            logger.exception("intent_classify_failed gen=%s", request.generation_id)
            return ClassifyIntentResponse(
                intent="reply_qa",
                reason=f"意图分类失败，回退为回复澄清：{e}",
            )
        return ClassifyIntentResponse(intent=result["intent"], reason=result["reason"])

    async def BrainstormTurn(
        self,
        request: BrainstormTurnRequest,
        context: grpc.aio.ServicerContext,
    ) -> BrainstormTurnResponse:
        """Run one agenda-driven clarification turn (task group 3).

        First call without ``generation_id`` creates a BrainstormSession and
        returns its id; subsequent calls pass it back. Returns discrete
        manager_message cards (no SSE) + convergence state.
        """
        from .brainstorm import get_or_create_session, turn as brainstorm_turn

        try:
            # 与 classify_intent 同模式（fix #4）：显式 provider 实例直接线程化
            # 进 turn()，绝不 set_provider——避免并发 graph 流式过程中共享单例被换掉。
            provider = resolve_provider(request.model or "glm-5.2")

            # 7.6: 会话挂 user 维度 (BrainstormTurnRequest 无 metadata 字段,
            # 默认 "default" —— GenerateRequest 的 metadata.user_id 走 graph 侧)。
            session = get_or_create_session(request.generation_id, user_id="default")
            result = await brainstorm_turn(
                session,
                request.text,
                request.item_id,
                provider=provider,
            )
            proto_events = [
                ProtoGraphEvent(
                    event_type=ev["event_type"],
                    stage=ev["stage"],
                    data=json.dumps(ev["data"], ensure_ascii=False),
                )
                for ev in result["events"]
            ]
            return BrainstormTurnResponse(
                generation_id=result["generation_id"],
                converged=result["converged"],
                coverage=result["coverage"],
                events=proto_events,
            )
        except Exception:
            logger.exception("brainstorm_turn_failed gen=%s", request.generation_id)
            raise

    def get_runner(self, generation_id: str) -> GraphRunner | None:
        """Get active GraphRunner for external operations (E2E result, confirmation)."""
        return self._active_runners.get(generation_id)

    @staticmethod
    def _event_to_response(event: dict) -> GenerateResponse:
        """Convert a GraphRunner event dict to a GenerateResponse with GraphEvent."""
        return GenerateResponse(
            graph_event=ProtoGraphEvent(
                event_type=event["event_type"],
                stage=event["stage"],
                data=json.dumps(event["data"], ensure_ascii=False),
            )
        )
