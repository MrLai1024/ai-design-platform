from typing import TypedDict, Literal, NotRequired


class DispatchContract(TypedDict):
    """Dispatch handed to each worker (D3): {task_id, 输入引用, 验收标准, 工具边界, 约束}.

    ``tier`` / ``roles`` are set on the code-phase dispatch (task 5.1): the
    S/M/L complexity tier and the D6 role configuration chosen for it.
    """
    task_id: str
    input_ref: str
    acceptance_criteria: list[str]
    tool_bounds: list[str]
    constraints: list[str]
    tier: NotRequired[str]
    roles: NotRequired[list[str]]


# Single source of truth for the design worker's dispatch (D3/D5) — the
# Manager gates against these acceptance criteria: L1 Spec field completeness
# (4.3) + L2 Spec↔PRD coverage (4.4). Used by the graph phase-2 entry.
DESIGN_DISPATCH_CONTRACT: DispatchContract = {
    "task_id": "design",
    "input_ref": "analysis_result",
    "acceptance_criteria": ["Spec 字段完整", "Spec 覆盖 PRD 功能点"],
    "tool_bounds": [],
    "constraints": [],
}


class E2ETarget(TypedDict):
    by: Literal["testid", "text", "role", "css"]
    value: str


class E2ETestStep(TypedDict):
    action: Literal["click", "input", "assert", "wait"]
    target: E2ETarget       # structured selector (6.2: testid → text → role → css)
    value: str | None       # input value / expected text / wait ms
    assertion: NotRequired[Literal["contains", "equals", "exists"]]
    timeout: NotRequired[int]
    description: NotRequired[str]


class E2ETestCase(TypedDict):
    id: str
    requirement_id: str
    scenario: str
    steps: list[E2ETestStep]
    requires_browser: NotRequired[bool]   # 6.7: skipped in-phase, manual list


class E2EEvidence(TypedDict):
    dom_snapshot: NotRequired[str | None]
    console_errors: NotRequired[list[str]]
    network_errors: NotRequired[list[str]]
    screenshot_note: NotRequired[str]


class E2ECaseResult(TypedDict):
    case_id: str
    passed: bool
    error: str | None
    status: NotRequired[Literal["passed", "failed", "skipped_requires_browser"]]
    screenshot: str | None
    evidence: NotRequired[E2EEvidence | None]


class FailureDetails(TypedDict):
    source: Literal["e2e"]
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


class RunContext(TypedDict, total=False):
    """短期记忆 run_context (D8 ①) — 本次运行的轻量结构化快照.

    在各阶段切换时更新,并写透到 ``.ai-memory/state/run_context.json``
    (暂存区 — 崩溃恢复与 U9 使用): 当前议程/假设/决策引用、活动节点、
    阶段阶段、最近一次把关裁决、最近一次问题记录。
    """
    generation_id: str
    stage: str                            # 当前阶段 analysis|design|code|e2e
    phase: str                            # generating|reviewing|complete|...
    active_node: str                      # 当前活动节点 (planner|executor|gate|...)
    agenda: list[dict]                    # 头脑风暴议程摘要 [{id, topic, status}]
    assumptions: list[dict]               # 假设清单
    decisions: list[dict]                 # 决策日志 (brainstorm_decisions)
    latest_verdict: dict | None           # 最近一次 Manager 把关 {node, decision, reason}
    latest_problem: dict | None           # 最近一次问题 {category, problem, result}
    updated_at: str


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

    # Identity (task group 7): generation_id derives the persistent app dir
    # (data/generated/<app_id>); user_id keys the long-term user memory.
    generation_id: NotRequired[str]
    user_id: NotRequired[str]

    # Requirements analysis structured state (JSON-serialized RequirementsState)
    requirements_state_json: str | None

    # Brainstorm (agenda clarification, task group 3) products — set when the
    # generation_id maps to a converged BrainstormSession.
    brainstorm_decisions: NotRequired[list[dict]]    # 决策日志（方案选择及理由）
    brainstorm_assumptions: NotRequired[list[dict]]  # 假设清单（未确认议程项）

    # Stage outputs
    analysis_result: str | None
    design_result: str | None
    code_result: str | None
    e2e_results: list[E2ECaseResult] | None

    # E2E test cases (generated in analysis)
    e2e_test_cases: list[E2ETestCase] | None

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

    # 短期记忆 run_context (D8 ①, task group 7) — 本次运行快照,写透到
    # .ai-memory/state/run_context.json 暂存区。
    run_context: NotRequired[RunContext]

    # Design document MD (for streaming, separate from design_result)
    design_doc: str | None

    # Architecture Spec (machine-readable design contract, D5) — the design
    # node's second product (4.2); the Manager's gating object (4.3 L1 / 4.4 L2).
    architecture_spec: dict | None

    # Code generation — multi-file project output
    generated_files: dict[str, str]            # filename -> code content
    compile_errors: list[dict] | None          # [{file, line, message}]

    # E2E test cases document
    e2e_test_cases_md: str | None              # Rendered MD summary for user review
    e2e_user_confirmed: bool                   # User confirmed test cases

    # ====== Test Designer / Diagnoser (task group 6) ======

    # Designer report (6.1): {requirement_points, cases, coverage, dropped,
    # errors, md, written, card_payload, card_content} — the coverage matrix
    # gate verdict lives in report["coverage"].
    e2e_designer_report: NotRequired[dict | None]

    # Coverage matrix gate payload (6.5): {rows, passed, gaps, ...}.
    e2e_coverage_matrix: NotRequired[dict | None]

    # Test Diagnoser outcome (6.4): {diagnoses, counts, rollback_case_ids,
    # manifest_present, manifest_updates}. Only rollback_case_ids (real
    # regressions) trigger the code rollback.
    e2e_diagnosis: NotRequired[dict | None]

    # Change manifest (task group U8 wires the producer; the Diagnoser MUST
    # work with it absent → default classification). Expected shape:
    # {changed_requirements: ["R-03"], changes: [{requirement_id, ...}]}.
    change_manifest: NotRequired[dict | None]

    # ====== Incremental development workflow (task group 8) ======

    # Incremental mode flag (servicer sets it from metadata incremental=true +
    # existing .ai-memory). When set, the graph entry runs the diff → manifest
    # → test-disposition confirmation flow and the pipeline phases adapt
    # (delta PRD framing / merged spec / delta planner tasks / regression e2e).
    incremental_mode: NotRequired[bool]

    # Loaded existing-app memory context (8.1): {summary, requirements,
    # requirements_size, spec, generated_files, e2e_cases, e2e_manifest,
    # features} — consumed by the diff classification and the delta prompts.
    incremental_context: NotRequired[dict | None]

    # Confirmed feature-point diff (8.1): {added, removed, removed_ids,
    # modified, unchanged, note}. Produced by classify_diff, consumed by the
    # manifest generation and the test impact analysis.
    incremental_diff: NotRequired[dict | None]

    # Draft test-impact dispositions awaiting confirmation (8.4):
    # [{case_id, requirement_id, disposition, reason}] — kept until the user
    # confirms; the confirmed list lands in ``test_dispositions``.
    incremental_dispositions: NotRequired[list[dict] | None]

    # Confirmed test-impact dispositions (8.4): [{case_id, requirement_id,
    # disposition: keep|update|retire|fix-selector, reason}] — applied before
    # the regression run (retire → archived, update → expected_broken) and
    # consumed by the e2e designer / regression accounting.
    test_dispositions: NotRequired[list[dict] | None]

    # The incremental change id (changes/<change_id>.json record).
    change_id: NotRequired[str]

    # ====== Planner + Executor ReAct fields ======
    planner_dag: TaskDAG | None                    # Planner 输出的任务 DAG
    planner_reflect_count: int                     # Planner 重规划次数
    context_summary: dict | None                   # 全局摘要 {key_exports: {...}, completed_tasks: [...]}

    # Complexity tier (task 5.1): "S" | "M" | "L", assessed rule-based from the
    # architecture Spec (design-doc fallback) at the start of the code phase.
    implementation_tier: NotRequired[str]

    # ====== Manager-worker orchestration (skeleton) ======

    # Dispatch handed to each worker (D3): {task_id, input_ref, acceptance_criteria, tool_bounds, constraints}
    dispatch_contract: DispatchContract | None

    # Gate verdict history:
    # [{node, decision: "pass"|"redo"|"rollback", reason, signature, at}]
    # Skeleton for problem records (task group 9); signature dedupes re-judged
    # unchanged outputs.
    manager_verdicts: list[dict]

    # Gate routing decision — next worker ("code" | "e2e") or "end" (set by manager_gate).
    manager_next: NotRequired[str]

    # ====== Verifier (5.4) + Debugger (5.5) fields ======

    # Verifier 四层信号结果 (5.4):
    # {l1_ok, l2_ok, l3_ok, hooks_ok, evidence: {compile_errors,
    # contract_violations, runtime_errors, hook_violations}, passed, tier}.
    # Consumed by the code gate (manager run_l1_checks) and the Debugger.
    verifier_result: NotRequired[dict | None]

    # Debugger 修复轮次 (5.5): [{round, signature, diagnosis, at}] — 证据签名
    # 重复出现即无进展，停止自动修复升级 Manager。
    debugger_rounds: NotRequired[list[dict]]

    # ====== Tester (5.6, L 档) ======

    # Tester 结果 (5.6): {generated: [{path, size}], executed, passed,
    # failures: [{file, message}], reason, runner}。Verifier L4 行为层消费；
    # executed=False 且 generated 非空 = 文档化 deferral（执行不可行，不伪造
    # 成功，也不判失败）。
    tester_result: NotRequired[dict | None]

    # ====== Problem recovery (task group 9): 失败分类 / 恢复阶梯 / 红线 ======

    # 恢复事件链 (9.1/9.2): 每次失败分类 + 阶梯决策 + 结果，追加式记录。
    # [{ts, node, category, confidence, reason, signature, output_signature,
    #   strategy, target, attempts, result: pending|resolved|stale|escalated}]
    recovery_events: NotRequired[list[dict]]

    # 每问题自主尝试次数 (9.3 红线): evidence signature → 自主轮次数。
    # 同一证据签名自主处理 ≤ MAX_AUTONOMOUS_ATTEMPTS (2) 轮后强制求援。
    problem_attempts: NotRequired[dict[str, int]]

    # 最近一次恢复决策摘要 — 卡面发射消费 (分类/策略/是否红线/是否范围变更)。
    recovery_last: NotRequired[dict | None]

    # 红线熔断标记 (9.3): 已向用户求援（继续自主/转人工），等待选择。
    # 用户选择「继续自主」resume 后清除并重置该签名的问题尝试计数。
    escalated_signature: NotRequired[str | None]

    # 待确认的范围变更 (9.3 红线): {note, node, signature} — 用户 confirm_card
    # 确认前 Manager 不得自行删减范围；resume 后视为已确认 → scope_change_approved。
    pending_scope_change: NotRequired[dict | None]

    # 用户已确认的范围变更 (resume 消费 pending_scope_change 后置位) —
    # 随重派反馈进入下一轮生成（design_gate_feedback 消费）。
    scope_change_approved: NotRequired[bool]
