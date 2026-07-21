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

from typing import AsyncIterator

from langgraph.graph import StateGraph, END
from langgraph.types import Command
from langgraph.checkpoint.memory import MemorySaver

from .state import GenerationState
from .nodes import (
    analysis_node,
    design_node,
    code_node,
    review_node,
    e2e_node,
)
from .harness import LoopControl

import structlog

logger = structlog.get_logger()


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
    workflow.add_node("code", code_node)
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

    async def run(
        self,
        state: GenerationState,
        generation_id: str,
    ) -> AsyncIterator[dict]:
        """
        Run the graph, yielding GraphEvent dicts for each state transition.
        PRD is streamed token-by-token before LangGraph takes over.
        """
        config = {"configurable": {"thread_id": generation_id}}
        max_iterations = 50
        iteration = 0

        # ── Phase 1: Stream PRD with reasoning in real-time ──
        if not state.get("analysis_result"):
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

        # ── Phase 3: Code generation ──
        if not state.get("code_result") and not state.get("generated_files"):
            from .nodes import code_node

            yield self._make_event("stage_start", "code", {"phase": "generating"})

            # Run code_node directly (it generates files via tool calls)
            updated_state = await code_node(state)

            generated_files = updated_state.get("generated_files", {})
            compile_errors = updated_state.get("compile_errors")

            # Stream generated files to frontend
            yield self._make_event("code_gen_start", "code", {
                "files": list(generated_files.keys()),
            })
            for path, content in generated_files.items():
                yield self._make_event("file_start", "code", {"path": path})
                chunk_size = 200
                for j in range(0, len(content), chunk_size):
                    yield self._make_event("file_chunk", "code", {
                        "path": path,
                        "content": content[j:j + chunk_size],
                    })
                yield self._make_event("file_complete", "code", {"path": path})

            yield self._make_event("code_gen_done", "code", {
                "total_files": len(generated_files),
                "compile_errors": len(compile_errors) if compile_errors else 0,
            })

            state["code_result"] = updated_state.get("code_result", "")
            state["generated_files"] = generated_files
            state["compile_errors"] = compile_errors
            state["stage_phase"] = "complete"

            yield self._make_event("stage_complete", "code", {
                "summary": f"Generated {len(generated_files)} files",
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
