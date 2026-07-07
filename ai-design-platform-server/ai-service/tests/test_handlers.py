"""Tests for node handler implementations."""

import asyncio

from app.services.workflow.handlers.code_handler import CodeHandler
from app.services.workflow.ir_types import NodeDef


class TestCodeHandler:
    """Verify CodeHandler execution and compilation."""

    def test_compile_returns_callable(self):
        """compile_to_langgraph should return a callable async function."""
        handler = CodeHandler()
        node_def = NodeDef(
            id="c1",
            type="code",
            label="Test Code",
            position={"x": 0, "y": 0},
            config={
                "language": "python",
                "code": "result = 42",
                "timeout": 10,
                "output_key": "my_output",
            },
        )

        fn = handler.compile_to_langgraph(node_def)
        assert fn is not None
        assert callable(fn)

    def test_execute_runs_code_and_returns_output(self):
        """execute() should run code in sandbox and return {output_key: result}."""
        handler = CodeHandler()

        result = asyncio.run(
            handler.execute(
                state={"a": 3, "b": 4},
                config={
                    "language": "python",
                    "code": "result = {'product': state['a'] * state['b']}",
                    "timeout": 10,
                    "output_key": "calc_result",
                },
            )
        )

        assert "calc_result" in result
        assert result["calc_result"] == {"product": 12}

    def test_compile_and_call_executes_code(self):
        """compile_to_langgraph produces a function that executes correctly."""
        handler = CodeHandler()
        node_def = NodeDef(
            id="c2",
            type="code",
            label="Compute",
            position={"x": 0, "y": 0},
            config={
                "language": "python",
                "code": "result = {'doubled': state['x'] * 2}",
                "timeout": 10,
                "output_key": "doubled_result",
            },
        )

        fn = handler.compile_to_langgraph(node_def)
        result = asyncio.run(fn({"x": 21}))

        assert result == {"doubled_result": {"doubled": 42}}

    def test_execute_resolves_state_templates(self):
        """Template placeholders in code should be resolved before execution."""
        handler = CodeHandler()

        result = asyncio.run(
            handler.execute(
                state={"name": "Alice", "age": 30},
                config={
                    "language": "python",
                    "code": (
                        "result = {"
                        "'greeting': "
                        "f'Hello {state[\"name\"]}, age {state[\"age\"]}'"
                        "}"
                    ),
                    "timeout": 10,
                    "output_key": "message",
                },
            )
        )

        assert result["message"]["greeting"] == "Hello Alice, age 30"
