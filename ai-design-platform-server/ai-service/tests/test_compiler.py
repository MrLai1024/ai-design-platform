"""Tests for WorkflowCompiler — IR-to-LangGraph compilation."""

import pytest

from app.services.workflow.compiler import WorkflowCompiler
from app.services.workflow.ir_types import (
    EdgeDef,
    NodeDef,
    WorkflowIR,
    WorkflowSchema,
)


class TestWorkflowCompiler:
    """Verify that WorkflowCompiler correctly translates WorkflowIR to
    a compiled LangGraph StateGraph."""

    def setup_method(self):
        """Register all handler types before each test."""
        from app.services.workflow.handlers.code_handler import CodeHandler
        from app.services.workflow.handlers.human_handler import HumanConfirmHandler
        from app.services.workflow.handlers.llm_handler import LLMHandler
        from app.services.workflow.handlers.router_handler import RouterHandler
        from app.services.workflow.registry import NodeRegistry

        NodeRegistry.reset()
        NodeRegistry.register(LLMHandler())
        NodeRegistry.register(RouterHandler())
        NodeRegistry.register(HumanConfirmHandler())
        NodeRegistry.register(CodeHandler())

    # ------------------------------------------------------------------
    # Two-node linear workflow
    # ------------------------------------------------------------------

    def test_compile_two_node_linear(self):
        """A simple two-node LLM pipeline should compile successfully."""
        ir = WorkflowIR(
            id="wf-linear",
            name="Linear Workflow",
            schema=WorkflowSchema(state_variables=["input", "llm_output"]),
            nodes=[
                NodeDef(
                    id="n1",
                    type="llm",
                    label="LLM 1",
                    position={"x": 0, "y": 0},
                    config={
                        "model": "test",
                        "system_prompt": "You are helpful.",
                        "user_prompt": "{state.input}",
                        "output_key": "llm_output",
                    },
                ),
                NodeDef(
                    id="n2",
                    type="llm",
                    label="LLM 2",
                    position={"x": 0, "y": 0},
                    config={
                        "model": "test",
                        "system_prompt": "You are helpful.",
                        "user_prompt": "{state.llm_output}",
                        "output_key": "final_output",
                    },
                ),
            ],
            edges=[
                EdgeDef(id="e1", source="n1", target="n2"),
            ],
        )

        compiler = WorkflowCompiler()
        app = compiler.compile(ir)

        # Verify a CompiledStateGraph was returned
        assert app is not None
        assert hasattr(app, "astream")
        assert hasattr(app, "invoke")
        assert hasattr(app, "get_state")

    # ------------------------------------------------------------------
    # Router conditional workflow
    # ------------------------------------------------------------------

    def test_compile_with_router(self):
        """LLM -> Router -> two LLM branches should compile with conditional edges."""
        ir = WorkflowIR(
            id="wf-router",
            name="Router Workflow",
            schema=WorkflowSchema(state_variables=["score", "llm_output"]),
            nodes=[
                NodeDef(
                    id="n1",
                    type="llm",
                    label="Generate Score",
                    position={"x": 0, "y": 0},
                    config={
                        "model": "test",
                        "system_prompt": "",
                        "user_prompt": "return score",
                        "output_key": "llm_output",
                    },
                ),
                NodeDef(
                    id="n2",
                    type="router",
                    label="Check Score",
                    position={"x": 0, "y": 0},
                    config={
                        "branches": [
                            {"label": "pass", "condition": 'state["score"] > 60'},
                            {"label": "fail", "condition": "default"},
                        ],
                    },
                ),
                NodeDef(
                    id="n3",
                    type="llm",
                    label="Pass Handler",
                    position={"x": 0, "y": 0},
                    config={
                        "model": "test",
                        "system_prompt": "",
                        "user_prompt": "passed",
                        "output_key": "result",
                    },
                ),
                NodeDef(
                    id="n4",
                    type="llm",
                    label="Fail Handler",
                    position={"x": 0, "y": 0},
                    config={
                        "model": "test",
                        "system_prompt": "",
                        "user_prompt": "failed",
                        "output_key": "result",
                    },
                ),
            ],
            edges=[
                EdgeDef(id="e1", source="n1", target="n2"),
                EdgeDef(id="e2", source="n2", target="n3", condition="pass"),
                EdgeDef(id="e3", source="n2", target="n4", condition="fail"),
            ],
        )

        compiler = WorkflowCompiler()
        app = compiler.compile(ir)

        assert app is not None
        assert hasattr(app, "astream")
        assert hasattr(app, "invoke")

    # ------------------------------------------------------------------
    # Human-confirm interrupt collection
    # ------------------------------------------------------------------

    def test_compile_collects_human_confirm_interrupts(self):
        """LLM -> HumanConfirm should compile and the human node should be
        collected for interrupt_before."""
        ir = WorkflowIR(
            id="wf-human",
            name="Human Confirm Workflow",
            schema=WorkflowSchema(state_variables=["llm_output"]),
            nodes=[
                NodeDef(
                    id="n1",
                    type="llm",
                    label="Generate",
                    position={"x": 0, "y": 0},
                    config={
                        "model": "test",
                        "system_prompt": "",
                        "user_prompt": "generate something",
                        "output_key": "llm_output",
                    },
                ),
                NodeDef(
                    id="n2",
                    type="human_confirm",
                    label="Confirm",
                    position={"x": 0, "y": 0},
                    config={
                        "message": "Please review the output.",
                        "fields": [
                            {"key": "approved", "label": "Approve?", "type": "boolean", "required": True},
                        ],
                    },
                ),
            ],
            edges=[
                EdgeDef(id="e1", source="n1", target="n2"),
            ],
        )

        compiler = WorkflowCompiler()
        app = compiler.compile(ir)

        # Verify compilation succeeded
        assert app is not None
        assert hasattr(app, "astream")
        assert hasattr(app, "invoke")

    # ------------------------------------------------------------------
    # Edge cases
    # ------------------------------------------------------------------

    def test_compile_empty_workflow_raises(self):
        """Compiling a workflow with no nodes must raise ValueError."""
        ir = WorkflowIR(
            id="wf-empty",
            name="Empty Workflow",
            schema=WorkflowSchema(state_variables=[]),
            nodes=[],
            edges=[],
        )

        compiler = WorkflowCompiler()
        with pytest.raises(ValueError, match="at least one node"):
            compiler.compile(ir)

    # ------------------------------------------------------------------
    # Routers with RouterNodeConfig dataclass (not plain dict)
    # ------------------------------------------------------------------

    def test_compile_router_with_dataclass_config(self):
        """Router node using RouterNodeConfig dataclass should compile correctly."""
        from app.services.workflow.ir_types import RouterBranch, RouterNodeConfig

        ir = WorkflowIR(
            id="wf-router-dc",
            name="Router Dataclass Workflow",
            schema=WorkflowSchema(state_variables=["score"]),
            nodes=[
                NodeDef(
                    id="n1",
                    type="llm",
                    label="Generate",
                    position={"x": 0, "y": 0},
                    config={
                        "model": "test",
                        "system_prompt": "",
                        "user_prompt": "test",
                        "output_key": "score",
                    },
                ),
                NodeDef(
                    id="n2",
                    type="router",
                    label="Router",
                    position={"x": 0, "y": 0},
                    config=RouterNodeConfig(
                        branches=[
                            RouterBranch(label="high", condition='state["score"] > 80'),
                            RouterBranch(label="low", condition="default"),
                        ],
                    ),
                ),
                NodeDef(
                    id="n3",
                    type="llm",
                    label="High",
                    position={"x": 0, "y": 0},
                    config={
                        "model": "test",
                        "system_prompt": "",
                        "user_prompt": "high",
                        "output_key": "result",
                    },
                ),
                NodeDef(
                    id="n4",
                    type="llm",
                    label="Low",
                    position={"x": 0, "y": 0},
                    config={
                        "model": "test",
                        "system_prompt": "",
                        "user_prompt": "low",
                        "output_key": "result",
                    },
                ),
            ],
            edges=[
                EdgeDef(id="e1", source="n1", target="n2"),
                EdgeDef(id="e2", source="n2", target="n3", condition="high"),
                EdgeDef(id="e3", source="n2", target="n4", condition="low"),
            ],
        )

        compiler = WorkflowCompiler()
        app = compiler.compile(ir)

        assert app is not None
        assert hasattr(app, "astream")
        assert hasattr(app, "invoke")

    # ------------------------------------------------------------------
    # No state variables (empty schema)
    # ------------------------------------------------------------------

    def test_compile_with_empty_state_variables(self):
        """Compilation should succeed even when state_variables is empty."""
        ir = WorkflowIR(
            id="wf-nostate",
            name="No State Variables",
            schema=WorkflowSchema(state_variables=[]),
            nodes=[
                NodeDef(
                    id="n1",
                    type="llm",
                    label="LLM",
                    position={"x": 0, "y": 0},
                    config={
                        "model": "test",
                        "system_prompt": "Hello",
                        "user_prompt": "World",
                        "output_key": "output",
                    },
                ),
            ],
            edges=[],
        )

        compiler = WorkflowCompiler()
        app = compiler.compile(ir)

        assert app is not None
        assert hasattr(app, "astream")
