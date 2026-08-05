"""File manipulation tools for code generation."""

import os
import structlog
from .registry import ToolResult

logger = structlog.get_logger()


def safe_project_path(project_root: str, path: str) -> str | None:
    """Normalize + guard a LLM-controlled project path (5.6 review M4).

    Rejects absolute paths, backslash tricks and ``..`` traversal; returns the
    safe absolute path, or None when rejected. 单一来源：tester.write_tests 与
    create_file/write_code/delete_file 共用此防护（并行 executor 下 LLM 控制
    的路径越界风险更高）。
    """
    if not path or not isinstance(path, str):
        return None
    norm = path.strip().replace("\\", "/")
    if norm.startswith("/") or ".." in norm.split("/"):
        return None
    root = os.path.abspath(project_root)
    full = os.path.abspath(os.path.join(root, *norm.split("/")))
    if full.startswith(root + os.sep):
        return full
    return None


async def create_file(project_root: str, path: str, language: str = "vue") -> ToolResult:
    """Create an empty file with skeleton."""
    full_path = safe_project_path(project_root, path)
    if full_path is None:
        return ToolResult(ok=False, error=f"非法路径被拒绝：{path}")
    os.makedirs(os.path.dirname(full_path), exist_ok=True)

    if os.path.exists(full_path):
        logger.warning("file_already_exists", path=path)
        return ToolResult(ok=True, data={"path": path, "created": False, "existed": True})

    with open(full_path, "w", encoding="utf-8") as f:
        f.write(f"// {path}\n")
    logger.info("file_created", path=path)
    return ToolResult(ok=True, data={"path": path, "created": True})


async def write_code(project_root: str, path: str, content: str) -> ToolResult:
    """Write code to a file."""
    full_path = safe_project_path(project_root, path)
    if full_path is None:
        return ToolResult(ok=False, error=f"非法路径被拒绝：{path}")
    os.makedirs(os.path.dirname(full_path), exist_ok=True)

    with open(full_path, "w", encoding="utf-8") as f:
        f.write(content)
    logger.info("file_written", path=path, size=len(content))
    return ToolResult(ok=True, data={"path": path, "size": len(content)})


async def delete_file(project_root: str, path: str) -> ToolResult:
    """Delete a file."""
    full_path = safe_project_path(project_root, path)
    if full_path is None:
        return ToolResult(ok=False, error=f"非法路径被拒绝：{path}")
    if os.path.exists(full_path):
        os.remove(full_path)
        logger.info("file_deleted", path=path)
        return ToolResult(ok=True, data={"path": path, "deleted": True})
    return ToolResult(ok=True, data={"path": path, "deleted": False, "reason": "not found"})
