"""Tests for SandboxExecutor — isolated code execution via subprocess."""

import pytest

from app.services.workflow.sandbox import SandboxExecutor


class TestSandboxExecutor:
    """Verify SandboxExecutor.execute() for happy paths and error cases."""

    # ------------------------------------------------------------------
    # Basic execution
    # ------------------------------------------------------------------

    def test_execute_python_returns_result(self):
        """Basic Python execution should capture the result variable."""
        result = SandboxExecutor.execute(
            language="python",
            code="result = {'sum': state['a'] + state['b']}",
            state={"a": 1, "b": 2},
        )
        assert result == {"sum": 3}

    def test_execute_captures_all_locals_when_no_result_variable(self):
        """Without a result variable, all non-dunder locals are captured."""
        result = SandboxExecutor.execute(
            language="python",
            code="x = 10\ny = x * 2",
            state={},
        )
        assert result == {"x": 10, "y": 20}

    def test_execute_has_access_to_state_and_json(self):
        """User code can access the state dict and json module."""
        result = SandboxExecutor.execute(
            language="python",
            code="result = {'keys': list(state.keys()), 'can_json': json is not None}",
            state={"a": 1, "b": 2},
        )
        assert result["keys"] == ["a", "b"]
        assert result["can_json"] is True

    def test_execute_returns_value_key_for_non_dict_result(self):
        """When result is a non-dict (e.g. int, str), wrap in {'value': ...}."""
        result = SandboxExecutor.execute(
            language="python",
            code="result = 42",
            state={},
        )
        assert result == {"value": 42}

    def test_execute_empty_code(self):
        """Empty code should return an empty dict (no locals set)."""
        result = SandboxExecutor.execute(
            language="python",
            code="",
            state={},
        )
        assert result == {}

    # ------------------------------------------------------------------
    # Timeout
    # ------------------------------------------------------------------

    def test_execute_timeout_kills(self):
        """Code that sleeps longer than timeout should raise TimeoutError."""
        with pytest.raises(TimeoutError, match="timed out"):
            SandboxExecutor.execute(
                language="python",
                code="import time; time.sleep(10)",
                state={},
                timeout=1,
            )

    # ------------------------------------------------------------------
    # Error handling
    # ------------------------------------------------------------------

    def test_execute_syntax_error_reported(self):
        """Syntax errors in user code should raise RuntimeError with details."""
        with pytest.raises(RuntimeError, match="SyntaxError"):
            SandboxExecutor.execute(
                language="python",
                code="result = {invalid python syntax!!!}",
                state={},
            )

    def test_execute_runtime_error_reported(self):
        """Runtime exceptions should raise RuntimeError with exception name."""
        with pytest.raises(RuntimeError, match="ZeroDivisionError"):
            SandboxExecutor.execute(
                language="python",
                code="result = 1 / 0",
                state={},
            )

    def test_execute_name_error_reported(self):
        """NameError (undefined variable) should raise RuntimeError."""
        with pytest.raises(RuntimeError, match="NameError"):
            SandboxExecutor.execute(
                language="python",
                code="result = undefined_var",
                state={},
            )

    # ------------------------------------------------------------------
    # Invalid language
    # ------------------------------------------------------------------

    def test_execute_unsupported_language_raises(self):
        """Unsupported language should raise ValueError."""
        with pytest.raises(ValueError, match="Unsupported language"):
            SandboxExecutor.execute(
                language="javascript",
                code="console.log('hello')",
                state={},
            )
