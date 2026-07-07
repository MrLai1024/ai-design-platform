"""SandboxExecutor — isolated Python code execution via subprocess.

Runs user-supplied Python code inside a constrained subprocess with:
- State injection via sys.argv JSON serialization
- Timeout enforcement via subprocess.run(timeout=...)
- Structured error reporting via JSON stderr
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any

import structlog

logger = structlog.get_logger()

_EXEC_SCRIPT = r"""
import json, sys
_state = json.loads(sys.argv[1])
_user_locals = {}
try:
    exec(sys.argv[2], {"state": _state, "json": json}, _user_locals)
    if "result" in _user_locals:
        output = _user_locals["result"]
    else:
        output = {k: v for k, v in _user_locals.items() if not k.startswith("__")}
    print(json.dumps(output, ensure_ascii=False, default=str))
except Exception as _e:
    print(json.dumps({"__error__": str(_e), "__type__": type(_e).__name__}), file=sys.stderr)
    sys.exit(1)
"""


class SandboxExecutor:
    """Execute Python code in an isolated subprocess with timeout support.

    Usage::

        result = SandboxExecutor.execute(
            language="python",
            code="result = {'sum': state['a'] + state['b']}",
            state={"a": 1, "b": 2},
            timeout=10,
        )
        # result == {"sum": 3}
    """

    MAX_TIMEOUT: int = 120

    @staticmethod
    def execute(
        language: str, code: str, state: dict, timeout: int = 30
    ) -> dict:
        """Run *code* in an isolated subprocess and return the captured result.

        Args:
            language: Programming language of the code (only "python" supported).
            code: Python source code to execute.
            state: Workflow state dict, available as the ``state`` variable.
            timeout: Maximum execution time in seconds (capped at MAX_TIMEOUT).

        Returns:
            A dict containing the ``result`` variable set by the user code,
            or all non-dunder local variables if ``result`` is not set.

        Raises:
            ValueError: If *language* is not supported.
            TimeoutError: If execution exceeds *timeout* seconds.
            RuntimeError: If the user code raises an exception.
        """
        if language != "python":
            raise ValueError(f"Unsupported language: {language}")

        timeout = min(timeout, SandboxExecutor.MAX_TIMEOUT)
        state_json = json.dumps(state, ensure_ascii=False)

        logger.info(
            "sandbox_execute",
            language=language,
            code_len=len(code),
            timeout=timeout,
        )

        try:
            proc = subprocess.run(
                [sys.executable, "-c", _EXEC_SCRIPT, state_json, code],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            raise TimeoutError(
                f"Code execution timed out after {timeout}s"
            )

        if proc.returncode != 0:
            stderr = proc.stderr.strip() or "(no output)"
            try:
                err = json.loads(stderr)
                raise RuntimeError(
                    f"{err.get('__type__', 'Error')}: {err.get('__error__', stderr)}"
                )
            except (json.JSONDecodeError, TypeError):
                raise RuntimeError(
                    f"Code execution failed:\n{stderr[:500]}"
                )

        stdout = proc.stdout.strip()
        try:
            result = json.loads(stdout)
            return result if isinstance(result, dict) else {"value": result}
        except json.JSONDecodeError:
            return {"stdout": stdout}


__all__ = ["SandboxExecutor"]
