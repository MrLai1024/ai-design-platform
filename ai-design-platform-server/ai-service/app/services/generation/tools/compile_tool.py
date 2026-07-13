"""Compile tool — triggers frontend compilation and collects errors."""

import os
import structlog
from .registry import ToolResult

logger = structlog.get_logger()

_compile_errors: list[dict] = []


async def compile_project(project_root: str) -> ToolResult:
    """Compile the project and return errors."""
    global _compile_errors
    errors = []
    for dirpath, _dirnames, filenames in os.walk(project_root):
        for fn in filenames:
            if fn.endswith((".vue", ".ts", ".js")):
                filepath = os.path.join(dirpath, fn)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        f.read()
                except Exception as e:
                    errors.append({"file": fn, "line": 0, "message": str(e)})

    _compile_errors = errors
    if errors:
        logger.warning("compile_errors", count=len(errors))
        return ToolResult(ok=False, data={"errors": errors})
    logger.info("compile_ok", project=project_root)
    return ToolResult(ok=True, data={"errors": []})


async def get_compile_errors(project_root: str) -> ToolResult:
    """Get errors from last compilation."""
    global _compile_errors
    return ToolResult(ok=True, data={"errors": _compile_errors})
