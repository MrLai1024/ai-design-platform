from typing import TypedDict, Literal, NotRequired


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
