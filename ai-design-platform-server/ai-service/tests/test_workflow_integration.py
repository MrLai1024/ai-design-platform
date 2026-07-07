"""Integration tests for the full workflow pipeline: IR -> Compile -> Run."""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.workflow.handlers.code_handler import CodeHandler
from app.services.workflow.handlers.human_handler import HumanConfirmHandler
from app.services.workflow.handlers.llm_handler import LLMHandler
from app.services.workflow.handlers.router_handler import RouterHandler
from app.services.workflow.registry import NodeRegistry
from app.services.workflow.servicer import WorkflowServicer, _active_runners, _workflow_store


class TestWorkflowIntegration:
    """End-to-end tests that exercise WorkflowServicer with a real compiler."""

    def setup_method(self):
        """Reset stores and re-register handlers before each test."""
        NodeRegistry.reset()
        NodeRegistry.register(LLMHandler())
        NodeRegistry.register(RouterHandler())
        NodeRegistry.register(HumanConfirmHandler())
        NodeRegistry.register(CodeHandler())
        _workflow_store.clear()
        _active_runners.clear()

    # ------------------------------------------------------------------
    # Full pipeline: save -> run -> verify event sequence
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_full_pipeline_run(self):
        """Compile and run a 2-node LLM pipeline end-to-end."""
        ir_dict = {
            "id": "wf-int-test",
            "name": "Integration Test",
            "schema": {"state_variables": ["s1", "s2"]},
            "nodes": [
                {
                    "id": "a",
                    "type": "llm",
                    "label": "Node A",
                    "position": {"x": 0, "y": 0},
                    "config": {
                        "model": "glm-5.2",
                        "system_prompt": "x",
                        "user_prompt": "x",
                        "output_key": "s1",
                    },
                },
                {
                    "id": "b",
                    "type": "llm",
                    "label": "Node B",
                    "position": {"x": 0, "y": 100},
                    "config": {
                        "model": "glm-5.2",
                        "system_prompt": "y",
                        "user_prompt": "y",
                        "output_key": "s2",
                    },
                },
            ],
            "edges": [{"id": "e1", "source": "a", "target": "b"}],
        }

        # Save the workflow
        result = await WorkflowServicer.save(ir_dict)
        wf_id = result["id"]
        assert wf_id == "wf-int-test"
        assert result["name"] == "Integration Test"

        # Run with mocked LLM
        with patch(
            "app.services.workflow.handlers.llm_handler._llm_generate",
            new_callable=AsyncMock,
        ) as mock_llm:
            mock_llm.return_value = "test output"

            events = []
            async for event in WorkflowServicer.run(wf_id, {}):
                events.append(event)

        # Verify event sequence
        event_types = [e["event_type"] for e in events]
        assert "workflow_start" in event_types
        assert event_types.count("stage_start") == 2
        assert event_types.count("stage_complete") == 2
        assert "workflow_complete" in event_types

        # Verify no errors
        assert "node_error" not in event_types
        assert "loop_break" not in event_types

        # Verify workflow_complete status
        complete_event = events[-1]
        assert complete_event["data"]["status"] == "completed"

    # ------------------------------------------------------------------
    # Workflow not found
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_run_nonexistent_workflow_returns_error(self):
        """Running a missing workflow ID should yield an error event."""
        events = []
        async for event in WorkflowServicer.run("nonexistent-id", {}):
            events.append(event)

        assert len(events) == 1
        assert events[0]["event_type"] == "node_error"
        assert "not found" in events[0]["data"]["error"].lower()

    # ------------------------------------------------------------------
    # CRUD operations
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_save_get_list_delete_workflow(self):
        """Workflow CRUD should work end-to-end."""
        ir_dict = {
            "id": "wf-crud",
            "name": "CRUD Test",
            "schema": {"state_variables": ["x"]},
            "nodes": [
                {
                    "id": "n1",
                    "type": "llm",
                    "label": "LLM",
                    "position": {"x": 0, "y": 0},
                    "config": {
                        "model": "glm-5.2",
                        "system_prompt": "p",
                        "user_prompt": "p",
                        "output_key": "x",
                    },
                },
            ],
            "edges": [],
        }

        # Save
        result = await WorkflowServicer.save(ir_dict)
        assert result["id"] == "wf-crud"

        # List
        workflows = await WorkflowServicer.list_workflows()
        assert len(workflows) == 1
        assert workflows[0]["id"] == "wf-crud"

        # Get
        wf = await WorkflowServicer.get("wf-crud")
        assert wf is not None
        assert wf["name"] == "CRUD Test"
        assert len(wf["nodes"]) == 1

        # Delete
        deleted = await WorkflowServicer.delete("wf-crud")
        assert deleted is True

        # Gone
        assert await WorkflowServicer.get("wf-crud") is None
        assert await WorkflowServicer.list_workflows() == []

    # ------------------------------------------------------------------
    # Cancel active run
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_cancel_active_run(self):
        """Cancel should remove the active runner."""
        ir_dict = {
            "id": "wf-cancel",
            "name": "Cancel Test",
            "schema": {"state_variables": []},
            "nodes": [],
            "edges": [],
        }
        await WorkflowServicer.save(ir_dict)

        # Manually register a runner to simulate an active run
        from app.services.workflow.runner import DynamicGraphRunner

        _active_runners["wf-cancel"] = DynamicGraphRunner()

        cancelled = await WorkflowServicer.cancel("wf-cancel")
        assert cancelled is True
        assert "wf-cancel" not in _active_runners

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_returns_false(self):
        """Cancel a non-running workflow should return False."""
        cancelled = await WorkflowServicer.cancel("no-such-run")
        assert cancelled is False

    # ------------------------------------------------------------------
    # Delete nonexistent
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_false(self):
        """Delete a missing workflow should return False."""
        deleted = await WorkflowServicer.delete("no-such-wf")
        assert deleted is False

    # ------------------------------------------------------------------
    # Resume without active run
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_resume_without_active_run_returns_error(self):
        """Resume when there is no active runner should yield an error."""
        ir_dict = {
            "id": "wf-no-run",
            "name": "No Run",
            "schema": {"state_variables": []},
            "nodes": [],
            "edges": [],
        }
        await WorkflowServicer.save(ir_dict)

        events = []
        async for event in WorkflowServicer.resume("wf-no-run", {"approved": True}):
            events.append(event)

        assert len(events) == 1
        assert events[0]["event_type"] == "node_error"
        assert "no active run" in events[0]["data"]["error"].lower()
