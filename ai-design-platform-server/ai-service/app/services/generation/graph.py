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

    # Compile with checkpointing and human-in-the-loop.
    # analysis runs immediately (user clicks "开始设计" to trigger graph start).
    # design/code/review/e2e pause for user confirmation between stages.
    checkpointer = MemorySaver()
    app = workflow.compile(
        checkpointer=checkpointer,
        interrupt_before=["design", "code", "review", "e2e"],
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
        Each dict has: {event_type, stage, data}
        """
        config = {"configurable": {"thread_id": generation_id}}
        max_iterations = 50
        iteration = 0

        async for event in self.app.astream(state, config):
            iteration += 1
            if iteration > max_iterations:
                yield self._make_event("loop_break", "", {
                    "reason": f"Exceeded max iterations ({max_iterations})",
                })
                break

            for node_name, node_output in event.items():
                yield self._make_event("stage_start", node_name, {"phase": "generating"})

                if node_name == "analysis":
                    analysis_result = node_output.get("analysis_result", "")
                    # Detect requirements engine metadata
                    if analysis_result and analysis_result.startswith("__REQ_EVENT__:"):
                        for evt in self._emit_requirement_events(analysis_result):
                            yield evt
                    elif analysis_result:
                        # PRD text — stream in chunks for frontend rendering
                        yield self._make_event("prd_generate_start", "analysis", {
                            "mode": "full",
                            "sections_count": 5,
                            "parent_version": None,
                        })
                        chunk_size = 80
                        for i in range(0, len(analysis_result), chunk_size):
                            chunk = analysis_result[i:i + chunk_size]
                            yield self._make_event("prd_section", "analysis", {
                                "section_key": "content",
                                "content": chunk,
                            })
                            yield self._make_event("doc_chunk", "analysis", {
                                "content": chunk,
                            })
                        yield self._make_event("prd_section_complete", "analysis", {
                            "section_key": "content",
                        })
                        yield self._make_event("prd_generate_done", "analysis", {
                            "version": 1,
                            "full_content": analysis_result,
                            "duration_ms": 0,
                        })

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

                if node_name in ("analysis", "design", "code", "review", "e2e"):
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
                        chunk_size = 80
                        for i in range(0, len(e2e_cases_md), chunk_size):
                            chunk = e2e_cases_md[i:i + chunk_size]
                            yield self._make_event("doc_chunk", "e2e", {
                                "content": chunk,
                            })
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

                if node_name == "analysis":
                    analysis_result = node_output.get("analysis_result", "")
                    if analysis_result and not analysis_result.startswith("__REQ_EVENT__:"):
                        yield self._make_event("prd_generate_start", "analysis", {
                            "mode": "full", "sections_count": 5, "parent_version": None,
                        })
                        chunk_size = 80
                        for i in range(0, len(analysis_result), chunk_size):
                            chunk = analysis_result[i:i + chunk_size]
                            yield self._make_event("prd_section", "analysis", {
                                "section_key": "content", "content": chunk,
                            })
                            yield self._make_event("doc_chunk", "analysis", {
                                "content": chunk,
                            })
                        yield self._make_event("prd_section_complete", "analysis", {
                            "section_key": "content",
                        })
                        yield self._make_event("prd_generate_done", "analysis", {
                            "version": 1, "full_content": analysis_result, "duration_ms": 0,
                        })

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

                if node_name in ("analysis", "design", "code", "review", "e2e"):
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
            "analysis": output.get("analysis_result", "")[:200] if output.get("analysis_result") else "",
            "design": output.get("design_result", "")[:200] if output.get("design_result") else "",
            "code": f"Generated {len(output.get('code_result', ''))} chars of code",
            "review": output.get("review_result", ""),
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
