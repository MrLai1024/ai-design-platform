from typing import TypedDict, Literal


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
