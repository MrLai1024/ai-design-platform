"""Compile tool — returns real bundler errors reported by the frontend preview.

前端 esbuild-wasm 打包器是唯一的真实编译源：它对完整工程做语法、
类型与 import 图校验，错误经 ReportCompileFeedback RPC 写入 ToolRegistry。
本工具不再做"文件可读性"假检查。
"""

import structlog
from .registry import ToolResult

logger = structlog.get_logger()


async def compile_project(project_root: str, frontend_errors: list[dict] | None = None) -> ToolResult:
    """Return the latest real compile result reported by the frontend bundler."""
    errors = frontend_errors or []
    if errors:
        logger.warning("compile_errors_from_frontend", count=len(errors))
        return ToolResult(ok=False, data={"errors": errors})
    logger.info("compile_ok_from_frontend", project=project_root)
    return ToolResult(ok=True, data={"errors": []})


async def get_compile_errors(project_root: str, frontend_errors: list[dict] | None = None) -> ToolResult:
    """Get errors from the latest frontend-reported compilation."""
    return ToolResult(ok=True, data={"errors": frontend_errors or []})
