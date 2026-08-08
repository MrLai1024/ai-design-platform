"""File manipulation tools for code generation."""

import os
import structlog
from .registry import ToolResult

logger = structlog.get_logger()


def safe_project_path(project_root: str, path: str) -> str | None:
    """Normalize + guard a LLM-controlled project path.

    Rejects absolute paths, backslash tricks and ``..`` traversal; returns the
    safe absolute path, or None when rejected. Shared by all file tools
    (write/read/list/search) — the LLM controls these paths, so traversal
    outside the project root must never be possible.
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


async def list_files(project_root: str, prefix: str = "") -> ToolResult:
    """List files in the project directory (paths relative to project_root)."""
    if not os.path.isdir(project_root):
        return ToolResult(ok=True, data={"files": [], "total": 0})
    results = []
    for root_dir, dirs, files in os.walk(project_root):
        # Skip hidden dirs like .ai-memory
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in sorted(files):
            if name.startswith("."):
                continue
            full = os.path.join(root_dir, name)
            rel = os.path.relpath(full, project_root).replace("\\", "/")
            if prefix and not rel.startswith(prefix.rstrip("/")):
                continue
            try:
                size = os.path.getsize(full)
            except OSError:
                size = 0
            results.append({"path": rel, "size": size})
    results.sort(key=lambda f: f["path"])
    return ToolResult(ok=True, data={"files": results, "total": len(results)})


async def read_file(project_root: str, path: str, max_chars: int = 20000) -> ToolResult:
    """Read a file from the project (with size cap to protect context)."""
    full_path = safe_project_path(project_root, path)
    if full_path is None:
        return ToolResult(ok=False, error=f"非法路径被拒绝：{path}")
    if not os.path.isfile(full_path):
        return ToolResult(ok=False, error=f"文件不存在：{path}")
    try:
        with open(full_path, "r", encoding="utf-8") as f:
            content = f.read(max_chars)
        truncated = False
        if os.path.getsize(full_path) > max_chars:
            truncated = True
        return ToolResult(ok=True, data={
            "path": path, "content": content, "truncated": truncated,
        })
    except UnicodeDecodeError:
        return ToolResult(ok=False, error=f"文件不是 UTF-8 文本：{path}")


async def search_project(project_root: str, query: str, max_results: int = 10) -> ToolResult:
    """Keyword search over project files — path match or content substring."""
    if not os.path.isdir(project_root):
        return ToolResult(ok=True, data={"results": [], "total": 0})
    q = query.lower()
    results = []
    for root_dir, dirs, files in os.walk(project_root):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in sorted(files):
            if name.startswith("."):
                continue
            full = os.path.join(root_dir, name)
            rel = os.path.relpath(full, project_root).replace("\\", "/")
            if q in rel.lower():
                results.append({"path": rel, "match": "path", "snippet": ""})
                continue
            try:
                with open(full, "r", encoding="utf-8") as f:
                    content = f.read()
            except (UnicodeDecodeError, OSError):
                continue
            idx = content.lower().find(q)
            if idx >= 0:
                start = max(0, idx - 80)
                snippet = content[start:idx + 200]
                results.append({"path": rel, "match": "content", "snippet": snippet})
            if len(results) >= max_results:
                break
        if len(results) >= max_results:
            break
    return ToolResult(ok=True, data={"results": results[:max_results], "total": len(results)})
