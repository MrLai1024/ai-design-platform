"""Compile tool — real compilation via the node-compiler worker.

The node-compiler service (esbuild bundle check + vue-tsc --noEmit) is the
authoritative compile source. The frontend esbuild-wasm feedback is preserved
as a supplementary signal (preview display) but is no longer the pass/fail
criterion: ``compile_project`` calls the worker directly and returns its real
result. Worker unreachable / empty project / no entry → explicit failure,
never a silent "compile passed".
"""

import os
import re

import httpx
import structlog

from .registry import ToolResult

logger = structlog.get_logger()

COMPILE_TIMEOUT_SECONDS = 60.0

# Errors produced by the compile infrastructure itself (worker unreachable,
# HTTP error, missing project dir, empty project, no entry) — NOT code defects.
# The executor must not feed these into the LLM repair loop (no code to fix);
# they surface as task failure / retry instead.
ENV_ERROR_KIND = "env"


def _env_error(message: str) -> dict:
    """A structured environment error (no file/line — nothing to fix in code)."""
    return {
        "file": "", "line": 0, "column": 0,
        "message": message, "source": "node-compiler", "kind": ENV_ERROR_KIND,
    }


def _ensure_absolute(project_root: str) -> str:
    """node-compiler is a separate process with its own cwd — the project path
    must be absolute or the worker reports '项目目录不存在'."""
    return os.path.abspath(project_root)


# "未找到入口文件" — the final compile found no entry (main.ts/App.vue),
# usually because the entry task was skipped by the dependency gate. That is
# a PLANNING GAP (files no task produced), NOT an infrastructure failure:
# it must trigger replan, never the env abort path (which dead-ends
# generation). The entry candidates ride as the missing paths.
_MISSING_ENTRY_RE = re.compile(r"未找到入口文件")
_MISSING_ENTRY_PATHS_RE = re.compile(r"未找到入口文件（需要\s*([^）]+)）")


def is_env_error(err: dict) -> bool:
    """True when an error entry is an environment/infrastructure error (nothing
    to fix in the generated code) rather than a real compile defect."""
    if err.get("source") == "node-compiler" and not err.get("file"):
        # Missing-entry errors are planning gaps, not infra failures — they
        # must trigger replan, never the env abort path. Checked BEFORE the
        # kind short-circuit: the worker tags missing-entry errors with
        # kind="env", which used to win here and dead-ended generation with
        # final_compile_abort instead of replanning the entry files.
        if re.search(_MISSING_ENTRY_RE, err.get("message", "")):
            return False
        return True
    if err.get("kind") == ENV_ERROR_KIND:
        return True
    return False


# "File not found in project: X" / "Could not resolve X" / vue-tsc
# "Cannot find module 'X'" — the referenced file simply doesn't exist yet.
# This is a PLANNING signal: a task generated code that imports a file no
# task produced — replan (add the missing file to the DAG) instead of having
# the executor blindly rewrite existing files.
_MISSING_FILE_RES = (
    r"Could not resolve",
    r"File not found in project",
    r"Cannot find module",
    _MISSING_ENTRY_RE.pattern,
)

# Extract the missing path from resolver error messages:
#   Could not resolve "./App.vue" | File not found in project: ./App.vue
#   Cannot find module './router' or its corresponding type declarations.
_MISSING_PATH_RE = re.compile(r"""['"]([^'"]+)['"]""")
# Unquoted variant: "File not found in project: ./router/index.ts"
_MISSING_PATH_UNQUOTED_RE = re.compile(r"File not found in project:\s*(\S+)")


def is_missing_file_error(err: dict) -> bool:
    """True when the error means "imported file does not exist (yet)". """
    msg = err.get("message", "")
    return any(re.search(pat, msg) for pat in _MISSING_FILE_RES)


def extract_missing_paths(errors: list[dict]) -> list[str]:
    """Collect referenced-but-missing PROJECT paths from resolver errors.

    Project specifiers — ./x, ../x and the @/ alias (→ src/) — are
    planning-gap signals; bare package specifiers (@element-plus/icons-vue,
    vue) are infra concerns handled by external/stubs, never replanned.
    """
    paths: list[str] = []
    for err in errors:
        if not is_missing_file_error(err):
            continue
        msg = err.get("message", "")
        # Missing-entry: extract the entry candidates ("需要 src/main.ts 或 App.vue")
        m = _MISSING_ENTRY_PATHS_RE.search(msg)
        if m:
            for raw in re.split(r"[、或,，]", m.group(1)):
                p = raw.strip()
                if p and p not in paths:
                    paths.append(p)
            continue
        m = _MISSING_PATH_RE.search(msg)
        if not m:
            m = _MISSING_PATH_UNQUOTED_RE.search(msg)
        if m:
            raw = m.group(1).strip()
            if raw.startswith("@/"):
                path = "src/" + raw[2:]
            elif raw.startswith("./") or raw.startswith("../"):
                path = raw.lstrip("./")
            else:
                continue
            if path and path not in paths:
                paths.append(path)
    return paths


def classify_compile_errors(errors: list[dict]) -> str:
    """Classify a batch of compile errors for the replan decision.

    Returns one of:
      "env"           — infrastructure errors only (nothing to fix in code)
      "missing_file"  — every error is a missing-import signal (planning gap:
                        no task produced the imported file)
      "code"          — real code defects (syntax / types / …)
    """
    if not errors:
        return "code"
    if all(is_env_error(e) for e in errors):
        return "env"
    if all(is_missing_file_error(e) for e in errors):
        return "missing_file"
    return "code"


def _worker_base_url() -> str:
    return os.environ.get("NODE_COMPILER_ADDR", "http://localhost:5199").rstrip("/")


async def compile_project(
    project_root: str,
    full: bool = False,
    entry: str | None = None,
    frontend_errors: list[dict] | None = None,
) -> ToolResult:
    """Compile the project via the node-compiler worker.

    Args:
        project_root: persistent project directory (source of truth).
        full: True → esbuild + vue-tsc; False → esbuild quick check only.
        entry: optional explicit entry (auto-detected by the worker).
        frontend_errors: kept for signature compatibility — the frontend
            esbuild feedback is display-only, not the pass/fail criterion.
    """
    url = f"{_worker_base_url()}/compile"
    payload = {"project_root": _ensure_absolute(project_root), "full": bool(full)}
    if entry:
        payload["entry"] = entry

    try:
        async with httpx.AsyncClient(timeout=COMPILE_TIMEOUT_SECONDS) as client:
            resp = await client.post(url, json=payload)
    except Exception as e:
        logger.error("compile_worker_unreachable", url=url, error=str(e))
        return ToolResult(
            ok=False,
            error=f"node-compiler 服务不可达 ({url}): {e}",
            data={"errors": [_env_error(f"node-compiler 服务不可达：{e}")]},
        )

    if resp.status_code != 200:
        logger.warning("compile_worker_http_error", status=resp.status_code, body=resp.text[:300])
        return ToolResult(
            ok=False,
            error=f"node-compiler 返回 {resp.status_code}",
            data={"errors": [_env_error(f"node-compiler 返回 {resp.status_code}: {resp.text[:200]}")]},
        )

    try:
        data = resp.json()
    except ValueError:
        logger.error("compile_worker_bad_json", body=resp.text[:300])
        return ToolResult(ok=False, error="node-compiler 响应不是合法 JSON")

    errors = data.get("errors") or []
    if data.get("partial"):
        # Partial: all errors are "Could not resolve" — dependencies of a
        # later task not generated yet (incremental generation). The executor
        # keeps going; NOT a failure (the task wrote everything it owns).
        # The unresolved paths ride along so graph.py can check whether the
        # missing files are planned by ANY task — if not, it's a planning gap
        # and the incremental replan must cover them.
        logger.info("compile_partial_from_worker", project=project_root, full=bool(full))
        return ToolResult(ok=True, data={"errors": [], "partial": True, "partial_paths": data.get("partial_paths", [])})
    if not data.get("ok") or errors:
        logger.warning("compile_errors_from_worker", count=len(errors))
        # Tag worker-reported infrastructure errors (no file → no code to fix)
        # so the executor can skip the LLM repair loop for them.
        for err in errors:
            if err.get("source") == "node-compiler" and "kind" not in err:
                err["kind"] = ENV_ERROR_KIND
        return ToolResult(ok=False, data={"errors": errors})
    logger.info("compile_ok_from_worker", project=project_root, full=bool(full))
    return ToolResult(ok=True, data={"errors": []})


async def get_compile_errors(
    project_root: str,
    full: bool = False,
    frontend_errors: list[dict] | None = None,
) -> ToolResult:
    """Get the latest compile result — same as compile_project (real check)."""
    return await compile_project(project_root, full=full)
