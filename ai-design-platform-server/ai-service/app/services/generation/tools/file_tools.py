"""File manipulation tools for code generation."""

import os
import structlog
from .registry import ToolResult

logger = structlog.get_logger()


async def create_file(project_root: str, path: str, language: str = "vue") -> ToolResult:
    """Create an empty file with skeleton."""
    full_path = os.path.join(project_root, path)
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
    full_path = os.path.join(project_root, path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)

    with open(full_path, "w", encoding="utf-8") as f:
        f.write(content)
    logger.info("file_written", path=path, size=len(content))
    return ToolResult(ok=True, data={"path": path, "size": len(content)})


async def delete_file(project_root: str, path: str) -> ToolResult:
    """Delete a file."""
    full_path = os.path.join(project_root, path)
    if os.path.exists(full_path):
        os.remove(full_path)
        logger.info("file_deleted", path=path)
        return ToolResult(ok=True, data={"path": path, "deleted": True})
    return ToolResult(ok=True, data={"path": path, "deleted": False, "reason": "not found"})
