"""Tests for workflow IR types — dataclass parsing, serialization, and template resolution."""

import json

import pytest

from app.services.workflow.ir_types import (
    CodeNodeConfig,
    EdgeDef,
    HumanConfirmField,
    HumanConfirmNodeConfig,
    LLMNodeConfig,
    NodeDef,
    RouterBranch,
    RouterNodeConfig,
    WorkflowIR,
    WorkflowSchema,
    resolve_template,
)


# ---------------------------------------------------------------------------
# TestNodeDef — node definitions and config parsing
# ---------------------------------------------------------------------------

class TestNodeDef:
    """NodeDef should parse its config dict into typed config dataclasses at init."""

    def test_llm_node_parses_config(self):
        """LLM node config dict becomes LLMNodeConfig with defaults populated."""
        node = NodeDef(
            id="n1",
            type="llm",
            label="Chat LLM",
            position={"x": 100, "y": 200},
            config={
                "model": "gpt-4o",
                "system_prompt": "You are helpful.",
                "user_prompt": "Hello {state.name}",
                "temperature": 0.3,
                "max_tokens": 2048,
                "output_key": "chat_result",
            },
        )

        assert node.id == "n1"
        assert node.type == "llm"
        assert node.label == "Chat LLM"
        assert node.position == {"x": 100, "y": 200}

        config = node.config
        assert isinstance(config, LLMNodeConfig)
        assert config.model == "gpt-4o"
        assert config.system_prompt == "You are helpful."
        assert config.user_prompt == "Hello {state.name}"
        assert config.temperature == 0.3
        assert config.max_tokens == 2048
        assert config.output_key == "chat_result"

    def test_llm_node_defaults(self):
        """LLM node with empty config should get default values."""
        node = NodeDef(
            id="n2",
            type="llm",
            label="Default LLM",
            position={"x": 0, "y": 0},
        )

        config = node.config
        assert isinstance(config, LLMNodeConfig)
        assert config.model == "glm-5.2"
        assert config.system_prompt == ""
        assert config.user_prompt == ""
        assert config.temperature == 0.7
        assert config.max_tokens == 4096
        assert config.output_key == "output"

    def test_router_node_parses_branches_with_default(self):
        """Router node config parses branch dicts into RouterBranch objects."""
        node = NodeDef(
            id="r1",
            type="router",
            label="Condition Router",
            position={"x": 300, "y": 100},
            config={
                "branches": [
                    {"label": "Pass", "condition": "state.review_passed == True"},
                    {"label": "Fail", "condition": "state.review_passed == False"},
                    {"label": "Default", "condition": "default"},
                ],
            },
        )

        config = node.config
        assert isinstance(config, RouterNodeConfig)

        branches = config.branches
        assert len(branches) == 3
        assert all(isinstance(b, RouterBranch) for b in branches)

        assert branches[0].label == "Pass"
        assert branches[0].condition == "state.review_passed == True"

        assert branches[1].label == "Fail"
        assert branches[1].condition == "state.review_passed == False"

        assert branches[2].label == "Default"
        assert branches[2].condition == "default"

    def test_human_confirm_node_parses_fields(self):
        """HumanConfirm node config parses field dicts into HumanConfirmField objects."""
        node = NodeDef(
            id="h1",
            type="human_confirm",
            label="Approve Design",
            position={"x": 500, "y": 300},
            config={
                "message": "Please review the design before proceeding.",
                "fields": [
                    {"key": "approved", "label": "Approved?", "type": "boolean", "required": True},
                    {"key": "comment", "label": "Comments", "type": "textarea", "required": False},
                ],
                "timeout": 600,
            },
        )

        config = node.config
        assert isinstance(config, HumanConfirmNodeConfig)

        assert config.message == "Please review the design before proceeding."
        assert config.timeout == 600

        fields = config.fields
        assert len(fields) == 2
        assert all(isinstance(f, HumanConfirmField) for f in fields)

        assert fields[0].key == "approved"
        assert fields[0].label == "Approved?"
        assert fields[0].type == "boolean"
        assert fields[0].required is True

        assert fields[1].key == "comment"
        assert fields[1].label == "Comments"
        assert fields[1].type == "textarea"
        assert fields[1].required is False

    def test_human_confirm_node_defaults(self):
        """HumanConfirm node with empty config should get default values."""
        node = NodeDef(
            id="h2",
            type="human_confirm",
            label="Confirm",
            position={"x": 0, "y": 0},
        )

        config = node.config
        assert isinstance(config, HumanConfirmNodeConfig)
        assert config.message == ""
        assert config.fields == []
        assert config.timeout == 300

    def test_code_node_config(self):
        """Code node config parses correctly."""
        node = NodeDef(
            id="c1",
            type="code",
            label="Run Python",
            position={"x": 400, "y": 200},
            config={
                "language": "python",
                "code": "print('hello')",
                "timeout": 60,
                "output_key": "python_result",
            },
        )

        config = node.config
        assert isinstance(config, CodeNodeConfig)
        assert config.language == "python"
        assert config.code == "print('hello')"
        assert config.timeout == 60
        assert config.output_key == "python_result"


# ---------------------------------------------------------------------------
# TestWorkflowIR — full workflow round-trip
# ---------------------------------------------------------------------------

class TestWorkflowIR:
    """WorkflowIR should serialize to/from JSON preserving all node configs."""

    SAMPLE_WORKFLOW_JSON = {
        "id": "wf-001",
        "name": "Code Review Workflow",
        "version": "1.0",
        "description": "A workflow that generates and reviews code.",
        "schema": {
            "input_schema": {"requirement": "string"},
            "output_schema": {"code": "string", "passed": "boolean"},
            "state_variables": ["requirement", "analysis_result", "code_result", "review_passed"],
        },
        "nodes": [
            {
                "id": "n1",
                "type": "llm",
                "label": "Analyze",
                "position": {"x": 100, "y": 100},
                "config": {
                    "model": "glm-5.2",
                    "system_prompt": "You are a requirements analyst.",
                    "user_prompt": "Analyze: {state.requirement}",
                    "temperature": 0.5,
                    "max_tokens": 4096,
                    "output_key": "analysis_result",
                },
            },
            {
                "id": "n2",
                "type": "code",
                "label": "Generate Code",
                "position": {"x": 300, "y": 100},
                "config": {
                    "language": "python",
                    "code": "def main():\n    pass",
                    "timeout": 30,
                    "output_key": "code_result",
                },
            },
            {
                "id": "r1",
                "type": "router",
                "label": "Check Result",
                "position": {"x": 500, "y": 100},
                "config": {
                    "branches": [
                        {"label": "Pass", "condition": "state.review_passed"},
                        {"label": "Fail", "condition": "default"},
                    ],
                },
            },
            {
                "id": "h1",
                "type": "human_confirm",
                "label": "Manual Review",
                "position": {"x": 700, "y": 100},
                "config": {
                    "message": "Please confirm the generated code.",
                    "fields": [
                        {"key": "approved", "label": "Approve", "type": "boolean", "required": True},
                    ],
                    "timeout": 300,
                },
            },
        ],
        "edges": [
            {"id": "e1", "source": "n1", "target": "n2"},
            {"id": "e2", "source": "n2", "target": "r1"},
            {"id": "e3", "source": "r1", "target": "h1", "condition": "Pass"},
            {"id": "e4", "source": "r1", "target": "n2", "condition": "Fail"},
        ],
    }

    def test_workflow_ir_roundtrip(self):
        """JSON -> WorkflowIR -> JSON should preserve all data."""
        data = json.loads(json.dumps(self.SAMPLE_WORKFLOW_JSON))

        wf = WorkflowIR.from_dict(data)

        # Top-level fields
        assert wf.id == "wf-001"
        assert wf.name == "Code Review Workflow"
        assert wf.version == "1.0"
        assert wf.description == "A workflow that generates and reviews code."

        # Schema
        schema = wf.schema
        assert isinstance(schema, WorkflowSchema)
        assert schema.input_schema == {"requirement": "string"}
        assert schema.output_schema == {"code": "string", "passed": "boolean"}
        assert schema.state_variables == [
            "requirement", "analysis_result", "code_result", "review_passed"
        ]

        # Nodes
        assert len(wf.nodes) == 4
        assert all(isinstance(n, NodeDef) for n in wf.nodes)

        # LLM node
        n1 = wf.nodes[0]
        assert n1.id == "n1"
        assert n1.type == "llm"
        assert isinstance(n1.config, LLMNodeConfig)
        assert n1.config.model == "glm-5.2"
        assert n1.config.output_key == "analysis_result"

        # Code node
        n2 = wf.nodes[1]
        assert n2.id == "n2"
        assert n2.type == "code"
        assert isinstance(n2.config, CodeNodeConfig)
        assert n2.config.language == "python"

        # Router node
        r1 = wf.nodes[2]
        assert r1.id == "r1"
        assert r1.type == "router"
        assert isinstance(r1.config, RouterNodeConfig)
        assert len(r1.config.branches) == 2

        # HumanConfirm node
        h1 = wf.nodes[3]
        assert h1.id == "h1"
        assert h1.type == "human_confirm"
        assert isinstance(h1.config, HumanConfirmNodeConfig)
        assert h1.config.timeout == 300

        # Edges
        assert len(wf.edges) == 4
        assert all(isinstance(e, EdgeDef) for e in wf.edges)
        assert wf.edges[0].source == "n1"
        assert wf.edges[0].target == "n2"
        assert wf.edges[3].condition == "Fail"
        assert wf.edges[0].condition is None  # e1 has no condition

        # Roundtrip back to dict
        out = wf.to_dict()
        assert isinstance(out, dict)
        assert out["id"] == "wf-001"
        assert out["name"] == "Code Review Workflow"
        assert len(out["nodes"]) == 4
        assert len(out["edges"]) == 4

        # Deep equality check — re-parse to confirm stability
        wf2 = WorkflowIR.from_dict(out)
        assert wf2.id == wf.id
        assert wf2.name == wf.name
        json1 = json.dumps(out, sort_keys=True)
        json2 = json.dumps(wf2.to_dict(), sort_keys=True)
        assert json1 == json2

    def test_empty_workflow(self):
        """Minimal WorkflowIR should work with defaults."""
        wf = WorkflowIR.from_dict({
            "id": "wf-min",
            "name": "Minimal Workflow",
        })
        assert wf.id == "wf-min"
        assert wf.version == "1.0"
        assert wf.description == ""
        assert wf.schema == WorkflowSchema()
        assert wf.nodes == []
        assert wf.edges == []

    def test_edge_def(self):
        """EdgeDef should optionally carry a condition."""
        e1 = EdgeDef(id="e1", source="a", target="b")
        assert e1.condition is None

        e2 = EdgeDef(id="e2", source="a", target="b", condition="state.ok")
        assert e2.condition == "state.ok"


# ---------------------------------------------------------------------------
# TestTemplateResolution — {state.xxx} placeholder substitution
# ---------------------------------------------------------------------------

class TestTemplateResolution:
    """resolve_template should replace {state.xxx} with state values."""

    def test_resolve_state_template(self):
        """Simple {state.key} should be replaced with the value."""
        template = "Hello {state.name}, welcome!"
        state = {"name": "Alice"}
        result = resolve_template(template, state)
        assert result == "Hello Alice, welcome!"

    def test_resolve_nested_state_key(self):
        """Dotted key {state.user.name} should resolve from nested dict."""
        template = "User: {state.user.name}, Age: {state.user.age}"
        state = {"user": {"name": "Bob", "age": 30}}
        result = resolve_template(template, state)
        assert result == "User: Bob, Age: 30"

    def test_resolve_multiple_placeholders(self):
        """Multiple placeholders in one string should all resolve."""
        template = "{state.greeting}, {state.subject}!"
        state = {"greeting": "Hello", "subject": "World"}
        result = resolve_template(template, state)
        assert result == "Hello, World!"

    def test_resolve_missing_key_keeps_placeholder(self):
        """Missing state keys should be left as-is (no substitution)."""
        template = "Key: {state.missing}"
        state = {"other": "value"}
        result = resolve_template(template, state)
        assert result == "Key: {state.missing}"

    def test_resolve_partial_missing_nested(self):
        """Partially missing nested key should keep placeholder."""
        template = "Name: {state.user.name}"
        state = {"user": {}}  # user exists but name does not
        result = resolve_template(template, state)
        assert result == "Name: {state.user.name}"

    def test_resolve_deeply_nested_key(self):
        """Deep nesting with triple dots should resolve."""
        template = "Value: {state.a.b.c}"
        state = {"a": {"b": {"c": 42}}}
        result = resolve_template(template, state)
        assert result == "Value: 42"

    def test_resolve_no_placeholders(self):
        """String without placeholders passes through unchanged."""
        template = "No placeholders here."
        result = resolve_template(template, {"a": 1})
        assert result == "No placeholders here."

    def test_resolve_non_string_value(self):
        """Non-string state values should be stringified via str()."""
        template = "Count: {state.count}"
        state = {"count": 42}
        result = resolve_template(template, state)
        assert result == "Count: 42"
