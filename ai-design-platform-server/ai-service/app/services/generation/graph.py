"""
LangGraph StateGraph definition for the 5-node multi-agent pipeline.

Topology:
    analysis -> design -> code -> review -> e2e
                   ^                 ^         |
                   |                 |         |
                   +--- critical ----+         |
                   |                           |
                   +--------- e2e fail --------+
                              (via code -> review -> e2e)
"""

import asyncio
import os as _os
from typing import AsyncIterator

from langgraph.graph import StateGraph, END
from langgraph.types import Command
from langgraph.checkpoint.memory import MemorySaver

from .state import GenerationState
from .nodes import (
    analysis_node,
    design_node,
    code_passthrough_node,
    review_node,
    e2e_node,
    planner_node,
    executor_task,
    planner_reflect_node,
)
from .harness import LoopControl

import structlog

logger = structlog.get_logger()

async def _stream_executor_events(gen_task, queue):
    """Drain executor events from the queue while the executor task runs."""
    while not gen_task.done() or not queue.empty():
        try:
            yield await asyncio.wait_for(queue.get(), timeout=0.1)
        except asyncio.TimeoutError:
            pass


def _apply_task_result(task, result, tasks, dag, state, generated_files, project_root):
    """Merge one executor result into the task/DAG/state/disk. Shared by the
    main planner loop and the final-compile repair loop."""
    task["status"] = result["status"]
    task["executor_summary"] = result["summary"]
    task["compile_errors"] = result["compile_errors"]
    task["failure_kind"] = result.get("failure_kind", "done")
    task["missing_paths"] = result.get("missing_paths", [])
    task["partial_paths"] = result.get("partial_paths", [])
    for path, content in result.get("generated_files", {}).items():
        generated_files[path] = content
        full_path = _os.path.join(project_root, path)
        _os.makedirs(_os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as wf:
            wf.write(content)
    dag["completed_tasks"] = sum(
        1 for t in tasks if t.get("status") in ("done", "failed")
    )
    state["planner_dag"] = dag
    state["generated_files"] = generated_files
    state["context_summary"] = state.get("context_summary", {"key_exports": {}, "completed_tasks": []})


def decide_after_review(state: GenerationState) -> str:
    """Conditional edge after review node."""
    if state.get("review_passed"):
        return "e2e"

    severity = state.get("review_severity", "minor")
    if severity == "critical":
        return "design"
    return "code"


def decide_after_e2e(state: GenerationState) -> str:
    """Conditional edge after e2e node."""
    if state.get("e2e_passed"):
        return END
    return "code"


def build_graph() -> StateGraph:
    """Build and return the compiled LangGraph StateGraph."""
    workflow = StateGraph(GenerationState)

    # Add nodes
    workflow.add_node("analysis", analysis_node)
    workflow.add_node("design", design_node)
    workflow.add_node("code", code_passthrough_node)
    workflow.add_node("review", review_node)
    workflow.add_node("e2e", e2e_node)

    # Entry point
    workflow.set_entry_point("analysis")

    # Forward edges
    workflow.add_edge("analysis", "design")
    workflow.add_edge("design", "code")
    workflow.add_edge("code", "review")

    # Conditional edges
    workflow.add_conditional_edges(
        "review",
        decide_after_review,
        {
            "e2e": "e2e",
            "code": "code",
            "design": "design",
        },
    )
    workflow.add_conditional_edges(
        "e2e",
        decide_after_e2e,
        {
            END: END,
            "code": "code",
        },
    )

    # analysis runs immediately, design runs immediately.
    # code/review/e2e pause for user confirmation between stages.
    checkpointer = MemorySaver()
    app = workflow.compile(
        checkpointer=checkpointer,
        interrupt_before=["code", "review", "e2e"],
    )

    return app


class GraphRunner:
    """Runs the LangGraph app and bridges gRPC streaming with frontend SSE."""

    def __init__(self):
        self.app = build_graph()
        self.loop_control = LoopControl()
        self._state: GenerationState | None = None
        self._active_registry = None  # ToolRegistry of the running code phase

    def report_compile_feedback(self, ok: bool, errors: list[dict] | None = None) -> bool:
        """Receive real bundler compile feedback from the frontend.

        Returns True if a code-phase registry is active to consume it.
        """
        if self._active_registry is None:
            return False
        self._active_registry.report_frontend_compile(ok, errors)
        return True

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
        config = {"configurable": {"thread_id": generation_id}}
        max_iterations = 50
        iteration = 0

        # ── Phase 1: Stream PRD with reasoning in real-time ──
        if not state.get("analysis_result"):
            logger.info("graph_run_phase1_start gen=%s", generation_id)
            import asyncio as _asyncio
            from .nodes import ANALYSIS_PRD_PROMPT, _llm_generate

            yield self._make_event("stage_start", "analysis", {"phase": "generating"})
            yield self._make_event("prd_generate_start", "analysis", {
                "mode": "full", "sections_count": 5, "parent_version": None,
            })

            requirement = state.get("requirement", "")
            messages = state.get("messages", [])
            context_parts = []
            for m in messages:
                context_parts.append(f"[{m.get('role', '?')}]: {m.get('content', '')}")
            context = "\n".join(context_parts)
            user_prompt = f"用户需求：{requirement}\n\n对话上下文：{context}\n\n请生成完整的需求规格文档。"

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
            yield self._make_event("human_confirm_required", "analysis", {
                "message": "Please review the analysis output.",
            })
            return  # Wait for user to click "下一步"

        else:
            logger.info("graph_run_phase1_skip gen=%s reason=analysis_result_already_set", generation_id)

        # ── Phase 2: Stream design doc (same streaming pattern as PRD) ──
        if not state.get("design_result"):
            import asyncio as _asyncio
            from .nodes import DESIGN_SYSTEM_PROMPT, _llm_generate

            yield self._make_event("stage_start", "design", {"phase": "generating"})
            yield self._make_event("design_gen_start", "design", {})

            prompt = f"需求分析文档：\n{state.get('analysis_result', '')}"

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

            # Kick off architecture-spec generation in the background — the
            # user reviews the design doc meanwhile; the planner awaits it
            # inside its own task, so the confirm click and the code-stage
            # entry are never blocked by spec generation.
            if state.get("analysis_result"):
                from .nodes import generate_architecture_spec, _spec_background_tasks

                _spec_background_tasks[generation_id] = asyncio.create_task(
                    generate_architecture_spec(
                        analysis_result=state["analysis_result"],
                        design_doc=design_full,
                    )
                )
                logger.info("architecture_spec_background_started gen=%s", generation_id)

            yield self._make_event("design_gen_done", "design", {
                "full_content": design_full,
            })
            yield self._make_event("stage_complete", "design", {
                "summary": design_full[:200] if design_full else "",
            })
            yield self._make_event("human_confirm_required", "design", {
                "message": "Please review the design output.",
            })
            return  # Wait for user to click "下一步"

        # ── Phase 3: Planner + Executor ReAct (streaming) ──
        if not state.get("generated_files"):
            import asyncio as _asyncio
            from .tools.registry import ToolRegistry
            import os as _os, json as _json
            from .state import resolve_project_root

            project_root = resolve_project_root(generation_id, state.get("requirement", ""))
            _os.makedirs(project_root, exist_ok=True)
            _safe_name = _os.path.basename(project_root)

            registry = ToolRegistry(project_root)
            self._active_registry = registry

            # Feedback replan: recover the project's actual files BEFORE the
            # planner runs — otherwise it sees an empty project and guesses.
            # The recovered set is also this round's baseline (executor merges
            # into it) so the next code_result stays complete across feedback
            # rounds. Empty on a first-time entry (nothing generated yet).
            from .state import restore_generated_files as _restore_files
            generated_files = _restore_files(state, project_root)
            if generated_files:
                state["generated_files"] = generated_files
                logger.info("feedback_project_restored gen=%s files=%s",
                            generation_id, len(generated_files))

            # Emit the code-stage entry event FIRST — the frontend switches to
            # the 功能开发 node immediately (规划中); the spec is awaited inside
            # the planner task, so the user never waits on the confirm click.
            yield self._make_event("stage_start", "code", {"phase": "planning"})
            state["generation_id"] = generation_id

            event_queue: _asyncio.Queue = _asyncio.Queue()

            # ── Step 1: Planner → Task DAG ──
            gen_task = _asyncio.create_task(planner_node(state, event_queue))

            while not gen_task.done() or not event_queue.empty():
                try:
                    evt = await _asyncio.wait_for(event_queue.get(), timeout=0.1)
                    yield evt
                except _asyncio.TimeoutError:
                    pass

            state = gen_task.result()
            dag = state.get("planner_dag", {})
            tasks = dag.get("tasks", [])

            if not tasks:
                # Feedback replan: an empty task list is the planner's explicit
                # "no changes needed" verdict — it reviewed the recovered
                # project state and judged nothing needs doing. Legitimate
                # outcome, not a dead end: proceed to the final-compile
                # arbitration (which re-checks everything anyway). Without
                # feedback an empty DAG is a real failure (nothing was planned
                # at all). Parse failures never reach here — planner_node
                # falls back to a non-empty scaffold DAG.
                from .planner import is_empty_delta_tolerable
                if is_empty_delta_tolerable(state.get("code_feedback"), True):
                    logger.info("feedback_no_changes gen=%s", generation_id)
                    yield self._make_event("planner_reflect", "code", {
                        "decision": "no_changes",
                        "failed_task_ids": [],
                    })
                else:
                    yield self._make_event("error", "code", {"reason": "Planner produced no tasks"})
                    return

            # generated_files baseline was set above (restore_files) — executor
            # merges new files into it; all_compile_errors tracks the latest.
            all_compile_errors: list[dict] | None = None
            max_planner_rounds = 3

            for planner_round in range(max_planner_rounds):
                # ── Step 2: Execute each pending task ──
                pending = [t for t in tasks if t.get("status") in ("pending", None)]

                for task in pending:
                    # Check deps satisfied
                    deps_ok = all(
                        any(
                            dt["id"] == dep_id and dt.get("status") == "done"
                            for dt in tasks
                        )
                        for dep_id in task.get("deps", [])
                    )
                    if not deps_ok:
                        continue  # Skip — dependencies not yet done

                    task["status"] = "running"

                    # Build executor context
                    registry.set_generated_files(generated_files)
                    state["generated_files"] = generated_files

                    exec_queue: _asyncio.Queue = _asyncio.Queue()
                    exec_gen_task = _asyncio.create_task(
                        executor_task(state, task, exec_queue, project_root, registry)
                    )
                    async for evt in _stream_executor_events(exec_gen_task, exec_queue):
                        yield evt
                    result = exec_gen_task.result()

                    if result.get("compile_errors"):
                        all_compile_errors = result["compile_errors"]
                    _apply_task_result(task, result, tasks, dag, state,
                                       generated_files, project_root)

                # ── Step 3: Planner REFLECT ──
                state["generated_files"] = generated_files
                reflect_queue: _asyncio.Queue = _asyncio.Queue()
                reflect_task = _asyncio.create_task(planner_reflect_node(state, reflect_queue))

                while not reflect_task.done() or not reflect_queue.empty():
                    try:
                        evt = await _asyncio.wait_for(reflect_queue.get(), timeout=0.1)
                        yield evt
                    except _asyncio.TimeoutError:
                        pass

                state = reflect_task.result()

                # ── Step 3.5: Planning-gap check — a DONE task imported files
                # (partial "Could not resolve") that NO task plans to produce.
                # Partial was tolerated so the task could finish; now check the
                # missing files against the planned set — unplanned ones are a
                # planning gap → merge into the replan request below.
                planned_files: set[str] = set()
                for t in tasks:
                    planned_files.update(t.get("files", []) or [])
                gap_paths: list[str] = []
                seen_gap: set[str] = set()
                for t in tasks:
                    for p in t.get("partial_paths", []) or []:
                        p_clean = p.lstrip("./")
                        if not p_clean or p_clean in seen_gap:
                            continue
                        is_planned = any(
                            f == p_clean or f.startswith(p_clean + "/")
                            for f in planned_files
                        )
                        if not is_planned:
                            gap_paths.append(p_clean)
                            seen_gap.add(p_clean)
                if gap_paths:
                    logger.info("planning_gap_detected gen=%s missing=%s",
                                generation_id, gap_paths)

                # ── Step 3.6: Execution-feedback replan — a task failed because
                # its code imports files no task produces (missing_file), OR the
                # planning-gap check above found unplanned partial imports.
                # Run the incremental planner to emit ONLY delta tasks for the
                # missing files, merge them into the DAG, then continue.
                replan = state.get("replan_request")
                missing_files: list[str] = []
                if replan:
                    missing_files = list(replan.get("missing_files", []))
                # merge gap paths into the replan (dedup)
                for p in gap_paths:
                    if p not in missing_files:
                        missing_files.append(p)
                if replan or gap_paths:
                    state["replan_request"] = None
                    if missing_files:
                        from .planner import (
                            PLANNER_SYSTEM_PROMPT,
                            build_incremental_planner_prompt,
                            extract_task_dag,
                            merge_delta_tasks,
                        )
                        from .nodes import _llm_generate

                        design_doc = state.get("design_doc") or state.get("design_result", "")
                        spec = state.get("architecture_spec")
                        replan_prompt = build_incremental_planner_prompt(
                            spec, design_doc, missing_files, generated_files,
                        )
                        logger.info("incremental_replan gen=%s missing=%s",
                                    generation_id, missing_files)
                        # Event carries data only (zero backend voice) — the
                        # frontend renders the status card per decision.
                        yield self._make_event("planner_reflect", "code", {
                            "decision": "replan_missing_files",
                            "missing_files": missing_files,
                            "failed_task_ids": replan.get("failed_task_ids", []) if replan else [],
                        })
                        raw = await _llm_generate(
                            system_prompt=PLANNER_SYSTEM_PROMPT,
                            user_content=replan_prompt,
                            enable_thinking=True,
                        )
                        try:
                            delta = extract_task_dag(raw)
                        except Exception as e:
                            # A parse failure is NOT the planner saying "no
                            # changes" — surface it instead of silently
                            # continuing with an empty delta (which would
                            # dead-end the loop later without a trace).
                            logger.error("incremental_replan_parse_failed", error=str(e))
                            yield self._make_event("error", "code", {
                                "reason": f"增量重规划输出解析失败: {e}",
                            })
                            return
                        # Renumber clashing ids (the incremental planner
                        # restarts at task-0) instead of dropping — a dropped
                        # delta means the missing file is never produced.
                        if delta.pop("truncated", False):
                            # A repaired tail means the delta itself is
                            # incomplete — never silent; the next compile
                            # round re-exposes whatever is still missing.
                            logger.warning("incremental_replan_truncated gen=%s", generation_id)
                        merged = merge_delta_tasks(tasks, delta.get("tasks", []))
                        dag["tasks"] = tasks
                        dag["total_tasks"] = len(tasks)
                        state["planner_dag"] = dag
                        logger.info("incremental_replan_merged gen=%s count=%s",
                                    generation_id, merged)
                        if merged:
                            # reasoning rides from the model's own output —
                            # never backend-assembled speech.
                            yield self._make_event("planner_dag", "code", {
                                "tasks": tasks,
                                "reasoning": delta.get("reasoning", ""),
                            })

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

            # ── Step 4: Final full compile + repair loop ──
            # The final compile (esbuild + vue-tsc) is the last gate — type
            # errors only surface here (executor quick checks skip vue-tsc),
            # and so do missing files that were never planned by any task.
            # Failure is fed BACK into the loop instead of stopping:
            #   missing_file → incremental replan (delta tasks for the files)
            #   code errors  → a repair task targeting the failing files,
            #                  executed with full-compile verification
            # Loop until compile passes, no new work can be added, or the
            # fix-round budget is exhausted.
            max_fix_rounds = 3
            fix_round = 0
            while fix_round < max_fix_rounds:
                compile_result = await registry.invoke("compile_project", {"full": True})
                compile_ok = compile_result.ok
                errors = compile_result.data.get("errors", []) if not compile_ok else []
                all_compile_errors = errors if not compile_ok else None

                yield self._make_event("compile_status", "code", {
                    "ok": compile_ok,
                    "errors": errors,
                })
                if compile_ok:
                    break

                from .planner import (
                    PLANNER_SYSTEM_PROMPT,
                    build_fix_task,
                    build_incremental_planner_prompt,
                    extract_task_dag,
                    merge_delta_tasks,
                    plan_final_compile_fix,
                )
                from .nodes import _llm_generate

                fix_plan = plan_final_compile_fix(errors, fix_round, max_fix_rounds)
                if fix_plan["action"] == "abort":
                    logger.warning("final_compile_abort", reason=fix_plan["reason"],
                                   errors=[e.get("message") for e in errors][:3])
                    yield self._make_event("planner_reflect", "code", {
                        "decision": "final_compile_abort",
                        "reason": fix_plan["reason"],
                    })
                    break

                if fix_plan["action"] == "replan":
                    design_doc = state.get("design_doc") or state.get("design_result", "")
                    spec = state.get("architecture_spec")
                    replan_prompt = build_incremental_planner_prompt(
                        spec, design_doc, fix_plan["missing_files"], generated_files,
                    )
                    logger.info("final_compile_replan gen=%s missing=%s",
                                generation_id, fix_plan["missing_files"])
                    yield self._make_event("planner_reflect", "code", {
                        "decision": "final_compile_replan",
                        "missing_files": fix_plan["missing_files"],
                    })
                    raw = await _llm_generate(
                        system_prompt=PLANNER_SYSTEM_PROMPT,
                        user_content=replan_prompt,
                        enable_thinking=True,
                    )
                    try:
                        delta = extract_task_dag(raw)
                    except Exception as e:
                        # Same rule as the main replan path: a parse failure is
                        # not "no changes" — surface it; the last compile
                        # errors stay recorded (all_compile_errors).
                        logger.error("final_compile_replan_parse_failed", error=str(e))
                        yield self._make_event("error", "code", {
                            "reason": f"最终编译修复重规划输出解析失败: {e}",
                        })
                        break
                    merged = merge_delta_tasks(tasks, delta.get("tasks", []))
                    dag["tasks"] = tasks
                    dag["total_tasks"] = len(tasks)
                    state["planner_dag"] = dag
                    logger.info("final_compile_replan_merged gen=%s count=%s",
                                generation_id, merged)
                    if delta.pop("truncated", False):
                        # Same rule as the main replan path: a repaired tail
                        # is an incomplete delta — surface it; the next fix
                        # round re-exposes whatever is still missing.
                        logger.warning("final_compile_replan_truncated gen=%s", generation_id)
                    if merged:
                        yield self._make_event("planner_dag", "code", {
                            "tasks": tasks,
                            "reasoning": delta.get("reasoning", ""),
                        })

                elif fix_plan["action"] == "fix":
                    fix_task = build_fix_task(fix_round, fix_plan["fix_files"], errors)
                    tasks.append(fix_task)
                    dag["tasks"] = tasks
                    dag["total_tasks"] = len(tasks)
                    state["planner_dag"] = dag
                    yield self._make_event("planner_reflect", "code", {
                        "decision": "final_compile_repair",
                        "fix_files": fix_plan["fix_files"],
                    })
                    # No model reasoning exists for a deterministic fix task —
                    # update the task list without touching the visible
                    # planner analysis (frontend keeps it when reasoning is
                    # absent).
                    yield self._make_event("planner_dag", "code", {
                        "tasks": tasks,
                    })

                # Execute the newly added tasks — fix tasks have no deps; delta
                # tasks may carry internal deps, so run the deps-satisfied ones
                # until nothing is left. Fix tasks verify via full compile
                # (vue-tsc) so the executor sees the type errors while it works.
                while True:
                    new_pending = [t for t in tasks if t.get("status") in ("pending", None)]
                    if not new_pending:
                        break
                    progressed = False
                    for task in new_pending:
                        deps_ok = all(
                            any(
                                dt["id"] == dep_id and dt.get("status") == "done"
                                for dt in tasks
                            )
                            for dep_id in task.get("deps", [])
                        )
                        if not deps_ok:
                            continue
                        progressed = True
                        task["status"] = "running"
                        registry.set_generated_files(generated_files)
                        state["generated_files"] = generated_files
                        exec_queue: _asyncio.Queue = _asyncio.Queue()
                        exec_gen_task = _asyncio.create_task(
                            executor_task(
                                state, task, exec_queue, project_root, registry,
                                compile_full=(task.get("type") == "fix"),
                            )
                        )
                        async for evt in _stream_executor_events(exec_gen_task, exec_queue):
                            yield evt
                        result = exec_gen_task.result()
                        if result.get("compile_errors"):
                            all_compile_errors = result["compile_errors"]
                        _apply_task_result(task, result, tasks, dag, state,
                                           generated_files, project_root)
                    if not progressed:
                        break  # delta-task dep deadlock → next compile reveals it
                fix_round += 1

            # Repair loop exhausted (or aborted) with errors still unresolved —
            # surface an explicit exit instead of silently ending: the user can
            # keep driving the agent via feedback (feedback → fresh-start →
            # recovered project state → replan). Decision carries data only.
            if not compile_ok:
                yield self._make_event("planner_reflect", "code", {
                    "decision": "needs_feedback",
                    "error_count": len(errors),
                })

            state["generated_files"] = generated_files
            state["compile_errors"] = all_compile_errors
            state["code_result"] = _json.dumps(generated_files, ensure_ascii=False)
            state["stage_phase"] = "complete"

            yield self._make_event("code_gen_done", "code", {
                "total_files": len(generated_files),
                "compile_errors": len(all_compile_errors) if all_compile_errors else 0,
                "app_name": _safe_name,
                "app_port": 8100 + (hash(_safe_name) % 100),
            })

            yield self._make_event("stage_complete", "code", {
                "summary": f"Generated {len(generated_files)} files in {len(tasks)} tasks",
            })
            yield self._make_event("human_confirm_required", "code", {
                "message": "Please review the code output.",
            })
            return

        # ── Phase 4: Run LangGraph for review and beyond ──
        async for event in self.app.astream(state, config):
            iteration += 1
            if iteration > max_iterations:
                yield self._make_event("loop_break", "", {
                    "reason": f"Exceeded max iterations ({max_iterations})",
                })
                break

            for node_name, node_output in event.items():
                yield self._make_event("stage_start", node_name, {"phase": "generating"})

                # analysis_node is only reached when pre-filled (Phase 2) — skip PRD events
                # design and beyond get normal streaming
                if node_name == "design":
                    design_doc = node_output.get("design_doc", "")
                    if design_doc:
                        yield self._make_event("design_gen_start", "design", {})
                        chunk_size = 80
                        for i in range(0, len(design_doc), chunk_size):
                            chunk = design_doc[i:i + chunk_size]
                            yield self._make_event("doc_chunk", "design", {
                                "content": chunk,
                            })
                        yield self._make_event("design_gen_done", "design", {
                            "full_content": design_doc,
                        })

                if node_name in ("design", "code", "review", "e2e"):
                    yield self._make_event("human_confirm_required", node_name, {
                        "message": f"Please review the {node_name} output and confirm to continue.",
                    })

                yield self._make_event("stage_complete", node_name, {
                    "summary": self._get_summary(node_name, node_output),
                })

                if node_name == "e2e":
                    e2e_cases_md = node_output.get("e2e_test_cases_md", "")
                    if e2e_cases_md:
                        yield self._make_event("e2e_cases_gen_start", "e2e", {})
                        for i in range(0, len(e2e_cases_md), 80):
                            chunk = e2e_cases_md[i:i + 80]
                            yield self._make_event("doc_chunk", "e2e", {"content": chunk})
                        yield self._make_event("e2e_cases_gen_done", "e2e", {
                            "full_content": e2e_cases_md,
                        })
                    elif node_output.get("e2e_user_confirmed"):
                        test_cases = node_output.get("e2e_test_cases", [])
                        yield self._make_event("e2e_execute_start", "e2e", {
                            "test_cases": test_cases,
                            "total": len(test_cases),
                        })
                        yield self._make_event("e2e_complete", "e2e", {
                            "passed": False,
                            "failed_count": 0,
                            "total_count": len(test_cases),
                        })

    async def resume(
        self,
        generation_id: str,
    ) -> AsyncIterator[dict]:
        """Resume the graph from its last interrupt point.

        Called after user clicks [下一步 ▸] to confirm a stage.
        """
        # If we haven't reached LangGraph Phase 4 yet (code not generated),
        # re-run manual phases — run() will skip completed phases.
        if self._state and not self._state.get("code_result"):
            async for event in self.run(self._state, generation_id):
                yield event
            return

        config = {"configurable": {"thread_id": generation_id}}
        max_iterations = 50
        iteration = 0

        async for event in self.app.astream(Command(resume=True), config):
            iteration += 1
            if iteration > max_iterations:
                yield self._make_event("loop_break", "", {
                    "reason": f"Exceeded max iterations ({max_iterations})",
                })
                break

            for node_name, node_output in event.items():
                yield self._make_event("stage_start", node_name, {"phase": "generating"})

                if node_name == "design":
                    design_doc = node_output.get("design_doc", "")
                    if design_doc:
                        yield self._make_event("design_gen_start", "design", {})
                        chunk_size = 80
                        for i in range(0, len(design_doc), chunk_size):
                            chunk = design_doc[i:i + chunk_size]
                            yield self._make_event("doc_chunk", "design", {
                                "content": chunk,
                            })
                        yield self._make_event("design_gen_done", "design", {
                            "full_content": design_doc,
                        })

                # Don't pause for analysis in Phase 2 (PRD already shown, user clicked next)
                if node_name in ("design", "code", "review", "e2e"):
                    yield self._make_event("human_confirm_required", node_name, {
                        "message": f"Please review the {node_name} output and confirm to continue.",
                    })

                yield self._make_event("stage_complete", node_name, {
                    "summary": self._get_summary(node_name, node_output),
                })

                if node_name == "e2e":
                    e2e_cases_md = node_output.get("e2e_test_cases_md", "")
                    if e2e_cases_md:
                        yield self._make_event("e2e_cases_gen_start", "e2e", {})
                        for i in range(0, len(e2e_cases_md), 80):
                            chunk = e2e_cases_md[i:i + 80]
                            yield self._make_event("doc_chunk", "e2e", {"content": chunk})
                        yield self._make_event("e2e_cases_gen_done", "e2e", {
                            "full_content": e2e_cases_md,
                        })

    async def resume_after_e2e(
        self,
        generation_id: str,
        e2e_results: list[dict],
    ) -> AsyncIterator[dict]:
        """Resume graph with E2E results and continue execution."""
        config = {"configurable": {"thread_id": generation_id}}
        try:
            current_state = self.app.get_state(config)
        except Exception as e:
            logger.error("get_state_failed", error=str(e))
            yield self._make_event("error", "e2e", {
                "reason": f"Failed to retrieve state: {str(e)}",
            })
            return

        passed = all(r.get("passed", False) for r in e2e_results)
        failed = [r for r in e2e_results if not r.get("passed", False)]

        yield self._make_event("e2e_complete", "e2e", {
            "passed": passed,
            "failed_count": len(failed),
            "total_count": len(e2e_results),
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
                yield self._make_event("loop_break", "e2e", {"reason": reason})
                # Force pass with manual review flag
                state_update = {
                    "e2e_results": e2e_results,
                    "e2e_passed": True,
                    "needs_manual_review": True,
                }
                self.app.update_state(config, state_update)
                return

            state_update = {
                "e2e_results": e2e_results,
                "e2e_passed": False,
                "failure_details": {
                    "source": "e2e",
                    "failed_items": failed,
                    "instruction": f"E2E 测试失败，以下用例未通过：\n{failed_text}",
                    "rollback_target": "code",
                },
            }
        else:
            state_update = {
                "e2e_results": e2e_results,
                "e2e_passed": True,
            }

        self.app.update_state(config, state_update)

        # Continue streaming from current state
        async for event in self.app.astream(None, config):
            for node_name, node_output in event.items():
                if node_name == "e2e":
                    continue
                yield self._make_event("stage_start", node_name, {})
                yield self._make_event("stage_complete", node_name, {
                    "summary": self._get_summary(node_name, node_output),
                })

    @staticmethod
    def _make_event(event_type: str, stage: str, data: dict) -> dict:
        return {"event_type": event_type, "stage": stage, "data": data}

    @staticmethod
    def _get_summary(node_name: str, output: dict) -> str:
        summaries = {
            "analysis": (output.get("analysis_result") or "")[:200],
            "design": (output.get("design_result") or "")[:200],
            "code": f"Generated {len(output.get('code_result') or '')} chars of code",
            "review": output.get("review_result") or "",
            "e2e": f"E2E: {'pass' if output.get('e2e_passed') else 'fail'}",
        }
        return summaries.get(node_name, "")

    def _emit_requirement_events(self, analysis_result: str):
        """Parse __REQ_EVENT__ metadata and yield requirement-specific events."""
        import json as _json
        try:
            meta_str = analysis_result[len("__REQ_EVENT__:"):]
            meta = _json.loads(meta_str)
        except Exception:
            return  # Not valid REQ_EVENT, skip

        layer_event = meta.get("layer_event", "")

        if layer_event == "requirement_layer_start":
            yield self._make_event("requirement_layer_start", "analysis", {
                "layer": meta.get("layer", 1),
                "label": meta.get("layer_label", ""),
                "total_layers": 3,
            })
        elif layer_event == "requirement_layer_done":
            yield self._make_event("requirement_layer_done", "analysis", {
                "layer": meta.get("completed_layer", 0),
                "summary": f"Layer {meta.get('completed_layer', 0)} completed — advancing to {meta.get('next_layer_label', '')}",
            })

        # Always emit card_update if there are questions (layer is active)
        questions = meta.get("questions", [])
        if questions:
            yield self._make_event("requirement_question", "analysis", {
                "questions": questions,
                "progress": meta.get("progress", {}),
            })

        # Always emit card_update with the full state
        yield self._make_event("requirement_card_update", "analysis", {
            "layer": meta.get("layer", 1),
            "mode": meta.get("mode", "new"),
            "version": meta.get("version", 0),
        })

        # Emit mode_set for tracking
        yield self._make_event("requirement_mode_set", "analysis", {
            "mode": meta.get("mode", "new"),
            "version": meta.get("version", 0),
        })
