import json
import os
import re
from typing import TypedDict, Literal, NotRequired


def extract_feedback_history(runner) -> dict:
    """Pull the previous run's live facts for the feedback replan.

    User feedback triggers a fresh-start; without these facts the planner
    would see an empty project (no files, no compile errors, no failed
    tasks) and guess. Returns pure data — consumed as planner prompt context,
    never shown verbatim as agent speech. Empty structure when no prior run
    is available (e.g. service restarted) — facts are never fabricated.
    """
    if runner is None or getattr(runner, "_state", None) is None:
        return {"compile_errors": [], "failed_tasks": []}
    old_state = runner._state
    failed_tasks = []
    for t in (old_state.get("planner_dag") or {}).get("tasks", []) or []:
        if t.get("status") == "failed":
            failed_tasks.append({
                "id": t.get("id"),
                "description": t.get("description", ""),
                "failure_kind": t.get("failure_kind", "code"),
                "missing_paths": t.get("missing_paths", []) or [],
            })
    return {
        "compile_errors": old_state.get("compile_errors") or [],
        "failed_tasks": failed_tasks,
    }


# Upper bound for the disk-scan fallback — a huge generated dir must not
# stall the feedback replan; the code_result path (complete, authoritative)
# covers normal flows anyway.
MAX_RESTORE_FILES = 500


def restore_generated_files(state, project_root: str) -> dict:
    """Recover the project's generated files for a feedback replan.

    Sources, most complete first:
    1. ``state["code_result"]`` — JSON serialization of generated_files
       written at the end of the code phase; the fresh-start prefill carries
       it back.
    2. Disk scan of the persistent project dir (dot-dirs skipped, bounded).

    Returns {path: content}; never raises. The result becomes the baseline of
    the new code phase so the next code_result stays complete.
    """
    code_result = state.get("code_result")
    if code_result:
        try:
            parsed = json.loads(code_result)
        except (ValueError, TypeError):
            parsed = None
        if isinstance(parsed, dict):
            return {p: c for p, c in parsed.items() if isinstance(c, str)}
    return scan_project_files(project_root)


def scan_project_files(project_root: str) -> dict:
    """Read all project files under a root (skip dot-dirs, bounded)."""
    files: dict[str, str] = {}
    if not os.path.isdir(project_root):
        return files
    for dirpath, dirnames, filenames in os.walk(project_root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            if len(files) >= MAX_RESTORE_FILES:
                return files
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, project_root).replace("\\", "/")
            try:
                with open(full, "r", encoding="utf-8") as f:
                    files[rel] = f.read()
            except (OSError, UnicodeDecodeError):
                continue  # binary/undecodable — skip
    return files


def resolve_project_root(generation_id: str | None, requirement: str = "") -> str:
    """Resolve the persistent project directory for a generation.

    Single source of truth for generated files: ``<AI_GEN_DATA_DIR>/<app_id>/``
    (default ``data/generated/<app_id>/`` under the ai-service cwd).

    ALWAYS returns an ABSOLUTE path — the path is consumed across processes
    (node-compiler worker, gateway) whose cwd differs from ai-service's.
    app_id = generation_id when present, else a sanitized requirement slug.
    """
    base = os.path.abspath(os.environ.get("AI_GEN_DATA_DIR", "data/generated"))
    if generation_id:
        app_id = re.sub(r"[^\w-]", "_", generation_id)[:64].strip("_") or "gen"
    else:
        raw = (requirement or "project")[:30]
        app_id = re.sub(r"[\W_]+", "_", raw)[:30].strip("_") or "ai-gen-project"
    return os.path.join(base, app_id)


class E2ETestStep(TypedDict):
    action: Literal["click", "input", "assert", "wait"]
    target: str          # CSS selector
    value: str | None    # input value / expected text / wait ms
    description: str


class E2ETestCase(TypedDict):
    id: str
    name: str
    description: str
    steps: list[E2ETestStep]


class E2ECaseResult(TypedDict):
    case_id: str
    passed: bool
    error: str | None
    screenshot: str | None


class FailureDetails(TypedDict):
    source: Literal["review", "e2e"]
    failed_items: list[dict]
    instruction: str
    rollback_target: Literal["code", "design"]


class RollbackRecord(TypedDict):
    rollback_id: str
    from_node: str
    to_node: str
    reason: str
    previous_output_hash: str
    token_cost: int


class PlannerTask(TypedDict):
    id: str                          # "task-0", "task-1", ...
    type: Literal["bootstrap", "business"]
    description: str                 # 人类可读描述
    deps: list[str]                  # 依赖的 task id 列表
    files: list[str]                 # 需要生成的文件路径
    contract: dict                   # { exports: [...], props: {...}, events: [...] }
    status: Literal["pending", "running", "done", "failed"]
    executor_summary: NotRequired[str]
    compile_errors: NotRequired[list[dict]]


class TaskDAG(TypedDict):
    tasks: list[PlannerTask]
    generated_at: str
    total_tasks: int
    completed_tasks: int


class GenerationState(TypedDict):
    # User input
    requirement: str
    component_lib: str
    messages: list[dict]

    # Requirements analysis structured state (JSON-serialized RequirementsState)
    requirements_state_json: str | None

    # Stage outputs
    analysis_result: str | None
    design_result: str | None
    code_result: str | None
    review_result: str | None
    e2e_results: list[E2ECaseResult] | None

    # E2E test cases (generated in analysis)
    e2e_test_cases: list[E2ETestCase] | None

    # Review status
    review_passed: bool
    review_severity: Literal["minor", "moderate", "critical"] | None

    # E2E status
    e2e_passed: bool

    # Failure details for rollback
    failure_details: FailureDetails | None

    # Analysis Q&A rounds (multi-turn clarification before spec output)
    qa_rounds: int

    # Loop control
    rollback_records: list[RollbackRecord]
    rollback_count: dict[str, int]
    max_rollback_per_node: int
    max_rollback_total: int
    needs_manual_review: bool

    # ====== NEW: Full pipeline workflow fields ======

    # Stage phase tracking ("qa" | "generating" | "reviewing" | "complete")
    stage_phase: str

    # Design document MD (for streaming, separate from design_result)
    design_doc: str | None

    # Structured architecture spec (JSON, machine-readable design contract)
    architecture_spec: dict | None

    # Code generation — multi-file project output
    generated_files: dict[str, str]            # filename -> code content
    compile_errors: list[dict] | None          # [{file, line, message}]

    # Multi-agent review output
    review_agent_results: list[dict] | None    # [{agent_key, name, icon, issues: [...]}]
    review_report_html: str | None             # Merged HTML report
    review_issues: list[dict] | None           # Structured issue list [{severity, file, line, title, description, fix}]

    # E2E test cases document
    e2e_test_cases_md: str | None              # MD document for user review
    e2e_user_confirmed: bool                   # User confirmed test cases

    # ====== Planner + Executor ReAct fields ======
    planner_dag: TaskDAG | None                    # Planner 输出的任务 DAG
    planner_reflect_count: int                     # Planner 重规划次数
    context_summary: dict | None                   # 全局摘要 {key_exports: {...}, completed_tasks: [...]}

    # Execution-feedback replan: set by planner_reflect when a task failed
    # because generated code imports files no task produces (missing_file).
    # graph.py consumes it to run the incremental planner and merge delta tasks.
    replan_request: NotRequired[dict]              # {missing_files: [...], failed_task_ids: [...]}

    # Live facts of the previous run, injected on feedback fresh-start by the
    # servicer (extracted from the old runner BEFORE it is overwritten):
    # {compile_errors: [...], failed_tasks: [{id, description, failure_kind, missing_paths}]}
    # Feeds the planner's feedback prompt; never shown verbatim to the user.
    feedback_history: NotRequired[dict]
