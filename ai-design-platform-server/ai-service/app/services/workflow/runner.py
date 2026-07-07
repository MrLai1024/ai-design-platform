"""DynamicGraphRunner — compiles and streams LangGraph workflow execution."""

from __future__ import annotations

import asyncio

import structlog

from .compiler import WorkflowCompiler

logger = structlog.get_logger()


class DynamicGraphRunner:
    """Compiles a WorkflowIR into a LangGraph app and streams execution events.

    Usage::

        runner = DynamicGraphRunner()
        async for event in runner.run(ir, initial_state, thread_id):
            yield event  # SSE-compatible dict
    """

    def __init__(self) -> None:
        self.compiler = WorkflowCompiler()
        self._running_apps: dict[str, object] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(
        self, ir, initial_state: dict, thread_id: str
    ):
        """Compile *ir* and stream execution events via ``app.astream()``.

        Yields SSE-style event dicts:
        ``{"event_type": str, "stage": str, "data": dict}``
        """
        app = self.compiler.compile(ir)
        self._running_apps[thread_id] = app
        config = {"configurable": {"thread_id": thread_id}}

        yield self._event("workflow_start", "", {
            "workflow_id": ir.id,
            "workflow_name": ir.name,
            "nodes_count": len(ir.nodes),
        })

        max_iterations = 100
        iteration = 0

        try:
            async for event in app.astream(initial_state, config):
                iteration += 1
                if iteration > max_iterations:
                    yield self._event("loop_break", "", {
                        "reason": f"Exceeded max iterations ({max_iterations})",
                    })
                    break

                for node_name, node_output in event.items():
                    node_label = node_name
                    node_type = ""
                    for n in ir.nodes:
                        if n.id == node_name:
                            node_label = n.label
                            node_type = n.type
                            break

                    yield self._event("stage_start", node_name, {
                        "label": node_label,
                        "type": node_type,
                    })

                    if node_type == "human_confirm":
                        hn = next(
                            (n for n in ir.nodes if n.id == node_name), None
                        )
                        cfg = hn.config if hn else {}
                        yield self._event("human_confirm_required", node_name, {
                            "message": getattr(cfg, "message", cfg.get("message", "")),
                            "fields": getattr(cfg, "fields", cfg.get("fields", [])),
                            "timeout": getattr(cfg, "timeout", cfg.get("timeout", 300)),
                        })

                    yield self._event("stage_complete", node_name, {
                        "label": node_label,
                        "type": node_type,
                        "summary": self._summarize(node_type, node_output),
                    })

            yield self._event("workflow_complete", "", {"status": "completed"})
        except asyncio.CancelledError:
            yield self._event("workflow_complete", "", {"status": "cancelled"})
        except Exception:
            logger.exception("workflow_run_failed", thread_id=thread_id)
            yield self._event("node_error", "", {
                "error": "Workflow execution failed",
            })

    async def resume(
        self, thread_id: str, human_response: dict, ir
    ):
        """Resume a paused workflow after human confirmation.

        Updates the state with *human_response* and continues streaming
        from the point of interruption.
        """
        app = self._running_apps.get(thread_id)
        if app is None:
            app = self.compiler.compile(ir)
            self._running_apps[thread_id] = app

        config = {"configurable": {"thread_id": thread_id}}
        try:
            app.update_state(config, {"_human_response": human_response})
            async for event in app.astream(None, config):
                for node_name, node_output in event.items():
                    node_label = node_name
                    for n in ir.nodes:
                        if n.id == node_name:
                            node_label = n.label
                            break
                    yield self._event("stage_start", node_name, {
                        "label": node_label,
                    })
                    yield self._event("stage_complete", node_name, {
                        "label": node_label,
                        "summary": self._summarize("", node_output),
                    })
            yield self._event("workflow_complete", "", {"status": "completed"})
        except Exception:
            logger.exception("workflow_resume_failed")
            yield self._event("node_error", "", {
                "error": "Resume execution failed",
            })
        finally:
            self._running_apps.pop(thread_id, None)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _event(event_type: str, stage: str, data: dict) -> dict:
        return {"event_type": event_type, "stage": stage, "data": data}

    @staticmethod
    def _summarize(node_type: str, output: dict) -> str:
        """Extract a human-readable preview from a node's output dict."""
        if not output:
            return ""
        if node_type == "human_confirm":
            return "Waiting for confirmation"
        if node_type == "router":
            return "Routed"
        # Generic: return first meaningful value
        for k, v in output.items():
            if not k.startswith("_"):
                s = str(v)
                return s[:200] if len(s) > 200 else s
        return str(output)[:200]
