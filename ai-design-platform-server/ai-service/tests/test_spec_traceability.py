"""Task 11.1 — spec 场景逐条核对的程序化守卫.

解析 9 个 spec 的全部 ``#### Scenario`` 行, 断言:
1. 每个场景在 MATRIX 中有条目 (场景级覆盖完整, 无遗漏);
2. 每个 MATRIX 条目映射的测试函数真实存在 (可执行验证, 无空映射);
3. MATRIX 无孤儿行 (每个条目都能在 spec 中找到对应场景);
4. 场景总数与文档化的统计一致 (漂移守卫: spec 增删场景时本测试失败提醒更新矩阵)。

另含 6.2 场景的静态验证: worker 模块不得读写记忆 (不 import memory_db —
记忆层只存在于 Manager 层: servicer/graph/manager/memory/recovery/feedback/
brainstorm/incremental)。
"""

import importlib
import os
import re
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).parent

# ── 场景 → 覆盖测试矩阵 (与 openspec/.../spec-traceability.md 同步) ──
# 值: 测试引用列表, "模块::类::函数" 或 "模块::函数" (tests 包内)。

MATRIX: dict[str, list[tuple[str, list[str]]]] = {
    "coordinator-agent": [
        ("节点完成时 Manager 发言", [
            "test_manager_gate::test_gate_manual_stage_emits_verdict",
            "test_manager_gate::test_manager_verdict_events_emit_cards",
            "test_dialog::test_summary_card_event",
            "test_e2e_full_flow::test_full_flow_dialog_and_memory",
        ]),
        ("worker 不直接发言", [
            "test_e2e_full_flow::test_full_flow_dialog_and_memory",
            "test_dialog::test_card_events_share_single_event_type_shape",
        ]),
        ("分发包含验收标准", [
            "test_implementation_tier::test_build_code_dispatch_contract",
            "test_memory::test_constraints_consumed_in_prompts_and_dispatch",
            "test_e2e_full_flow::test_full_flow_dialog_and_memory",
        ]),
        ("工具边界约束", [
            "test_e2e_full_flow::test_full_flow_dialog_and_memory",
        ]),
        ("L1 硬规则失败", [
            "test_architecture_spec::test_l1_failure_skips_l2_and_evidences_redo",
            "test_manager_gate::test_run_l1_checks_analysis",
            "test_spec_schema::test_validate_spec_missing_field",
        ]),
        ("L3 发现跑偏", [
            "test_recovery::test_e2e_drift_rollbacks_code",
            "test_recovery::TestClassifyLLM::test_llm_classifies_design_missing_drift",
            "test_architecture_spec::test_evaluate_stage_l2_design_missing_surfaces_in_verdict_and_diagnosis",
            "test_failure_injection::test_drift_design_l2_redo_regenerates_with_feedback",
        ]),
        ("把关通过", [
            "test_manager_gate::test_gate_manual_stage_emits_verdict",
            "test_architecture_spec::test_phase2_dual_product_and_gate_pass",
        ]),
        ("把关先行于确认", [
            "test_manager_gate::test_runner_phase4_announce_message_matches_verdict",
            "test_recovery::test_i3_analysis_redo_clears_and_feeds_back",
        ]),
        ("澄清回答路由", [
            "test_brainstorm::test_answer_via_item_id_and_assumed_marking",
            "test_brainstorm::test_answer_supersedes_assumption",
        ]),
        ("产出反馈路由", [
            "test_brainstorm::test_proposal_phase_free_text_is_feedback_not_answer",
            "test_feedback::TestDisposeUserFeedback::test_omission_pends_redispatch_and_records_problem",
        ]),
        ("流程指令路由", [
            "test_dialog::test_classify_intent_all_vocab",
            "test_brainstorm::test_coverage_insufficient_does_not_converge",
        ]),
        ("产物区确认与对话框叙事并存", [
            "test_manager_gate::test_runner_phase4_gate_flow",
            "test_manager_gate::test_gate_manual_stage_emits_verdict",
        ]),
    ],
    "brainstorm-clarification": [
        ("议程项维护", [
            "test_brainstorm::test_agenda_item_to_dict",
            "test_brainstorm::test_answer_via_item_id_and_assumed_marking",
        ]),
        ("用户未答项标记假设", [
            "test_brainstorm::test_answer_via_item_id_and_assumed_marking",
            "test_brainstorm::test_answer_supersedes_assumption",
            "test_brainstorm::test_analysis_prd_prompt_mentions_assumptions_section",
        ]),
        ("首轮产出画像", [
            "test_brainstorm::test_first_turn_produces_profile_card_no_questions",
        ]),
        ("关键路径问题优先", [
            "test_brainstorm::test_question_round_asks_by_impact_design_first",
        ]),
        ("方案选择", [
            "test_brainstorm::test_proposal_choice_records_decision_and_offers_confirm",
            "test_brainstorm::test_proposal_regenerate",
        ]),
        ("方案对比缺席时不得收敛", [
            "test_brainstorm::test_confirm_request_blocker_proposal_when_coverage_met",
        ]),
        ("覆盖不足不收敛", [
            "test_brainstorm::test_coverage_insufficient_does_not_converge",
            "test_brainstorm::test_empty_agenda_coverage_zero_does_not_converge",
        ]),
        ("覆盖达标且用户确认", [
            "test_brainstorm::test_full_lifecycle_to_convergence",
            "test_brainstorm::test_short_pure_confirm_converges",
        ]),
        ("产出物完整", [
            "test_brainstorm::test_full_lifecycle_to_convergence",
            "test_brainstorm::test_stream_graph_loads_brainstorm_session_products",
            "test_brainstorm::test_graph_phase1_prd_consumes_clarification_products",
        ]),
    ],
    "architecture-spec": [
        ("双产物输出", [
            "test_architecture_spec::test_phase2_dual_product_and_gate_pass",
            "test_architecture_spec::test_generate_spec_valid_first_shot",
        ]),
        ("字段缺失判不通过", [
            "test_spec_schema::test_validate_spec_missing_field",
            "test_architecture_spec::test_l1_catches_missing_spec_fields",
        ]),
        ("字段完整判通过", [
            "test_spec_schema::test_validate_spec_full_valid",
            "test_architecture_spec::test_harness_spec_check_deterministic",
        ]),
        ("功能点遗漏", [
            "test_architecture_spec::test_l2_parses_missing_list",
            "test_architecture_spec::test_phase2_l2_failure_gate_fails_with_missing_list",
        ]),
        ("功能点全落地", [
            "test_architecture_spec::test_l2_pass",
            "test_architecture_spec::test_phase2_dual_product_and_gate_pass",
        ]),
        ("Planner 消费 Spec", [
            "test_implementation_tier::TestPlannerSpecDriven::test_user_prompt_built_from_spec",
            "test_implementation_tier::TestPlannerSpecDriven::test_system_prompt_no_hardcoded_heuristics",
        ]),
        ("目录与 Spec 不符", [
            "test_verifier_debugger::TestVerifierL2::test_contract_task_with_missing_files_fails",
            "test_verifier_debugger::TestVerifierL2::test_l2_dep_pair_violation",
        ]),
        ("用户选择写入决策", [
            "test_architecture_spec::test_generate_spec_consumes_clarification_products",
            "test_spec_schema::test_write_spec_to_memory_writes_file",
            "test_memory::test_brainstorm_proposal_choice_upserts_preference",
        ]),
    ],
    "function-implementation": [
        ("S 档最小配置", [
            "test_implementation_tier::TestAssessComplexity::test_s_simple_form_spec",
            "test_implementation_tier::test_build_code_dispatch_contract",
        ]),
        ("L 档完整配置", [
            "test_implementation_tier::TestAssessComplexity::test_l_permissions",
            "test_implementation_tier::test_build_code_dispatch_contract",
            "test_tester_parallel::TestFullLLoop::test_tester_failure_debugger_fix_retest_pass",
        ]),
        ("DAG 与 Spec 对齐", [
            "test_implementation_tier::TestPlannerSpecDriven::test_user_prompt_built_from_spec",
            "test_e2e_full_flow::test_full_flow_dialog_and_memory",
        ]),
        ("契约验收", [
            "test_implementation_tier::TestExecutorAcceptance",
            "test_verifier_debugger::TestVerifierL2::test_l2_detects_missing_export",
        ]),
        ("L1 编译失败", [
            "test_verifier_debugger::TestVerifierL1::test_l1_fails_on_frontend_compile_errors",
            "test_failure_injection::test_compile_error_verifier_fail_debugger_fix_pass",
        ]),
        ("L3 运行时失败", [
            "test_verifier_debugger::TestVerifierL3::test_l3_fails_on_reported_runtime_errors",
            "test_verifier_debugger::TestRuntimeFeedbackServicer::test_report_runtime_feedback_stores_on_runner",
        ]),
        ("四层全部通过", [
            "test_verifier_debugger::TestVerifierResultShape::test_result_shape",
            "test_e2e_full_flow::test_full_flow_dialog_and_memory",
        ]),
        ("契约违约修复", [
            "test_verifier_debugger::TestDebuggerFixRoundIntegration::test_fix_round_contract_violation_repairs_and_passes",
            "test_verifier_debugger::TestExecutorFixContext::test_fix_instructions_threaded_into_prompt",
        ]),
        ("无进展检测", [
            "test_verifier_debugger::TestDebuggerNoProgress::test_same_signature_is_no_progress",
            "test_verifier_debugger::TestGraphFixRoundLoop::test_fix_round_no_progress_breaks_and_gate_redoes",
            "test_failure_injection::test_repeated_failure_red_line_rescue_then_reset_pass",
        ]),
        ("关键元素埋点", [
            "test_verifier_debugger::TestScanHooks::test_flags_button_without_testid",
            "test_verifier_debugger::TestScanHooks::test_passes_with_testid",
        ]),
        ("钩子作为验收项", [
            "test_verifier_debugger::TestVerifierHooks::test_hooks_fail_and_evidence_carries_list",
            "test_verifier_debugger::TestDebuggerFixRoundIntegration::test_fix_round_hooks_violation_repairs_and_passes",
        ]),
    ],
    "e2e-verification": [
        ("覆盖矩阵门禁", [
            "test_e2e_designer::test_designer_coverage_gate_marks_gap",
        ]),
        ("全需求点覆盖", [
            "test_e2e_designer::test_designer_valid_cases_coverage_passes",
        ]),
        ("DSL 用例生成", [
            "test_e2e_designer::test_validate_case_ok",
            "test_e2e_designer::test_designer_valid_cases_coverage_passes",
        ]),
        ("非法 DSL 拒绝执行", [
            "test_e2e_designer::test_validate_case_rejects_bad_schema",
            "test_e2e_designer::test_designer_invalid_cases_repair_then_drop",
        ]),
        ("优先 testid", [
            "test_e2e_designer::test_selector_priority_in_prompt",
        ]),
        ("用户确认执行", [
            "test_manager_gate::test_runner_resume_gate_worker_gate_cycle",
            "test_manager_gate::test_gate_routes_e2e_no_results_to_pause_after_confirmed",
        ]),
        ("失败证据收集", [
            "test_e2e_diagnoser::test_failing_step_parsed_from_error_text_for_later_steps",
            "test_manager_gate::test_resume_after_e2e_rollback_announces_paused_worker",
        ]),
        ("等待条件", [
            "test_manager_gate::test_runner_resume_gate_worker_gate_cycle",
        ]),
        ("预期失效", [
            "test_e2e_diagnoser::test_expected_broken_when_manifest_declares_change",
            "test_manager_gate::test_runner_resume_after_e2e_diagnoser_flow",
            "test_manager_gate::test_gate_all_expected_broken_routes_to_end",
        ]),
        ("真实回归", [
            "test_e2e_diagnoser::test_assertion_mismatch_without_manifest_is_real_regression",
            "test_manager_gate::test_gate_routes_e2e_failed_results_to_code_rollback",
            "test_manager_gate::test_resume_after_e2e_rollback_announces_paused_worker",
        ]),
        ("复杂用例跳过", [
            "test_e2e_designer::test_designer_requires_browser_annotation_survives",
            "test_manager_gate::test_runner_resume_after_e2e_skipped_cases_pass",
            "test_manager_gate::test_run_l1_checks_e2e_skips_requires_browser",
        ]),
        ("用例写入仓库", [
            "test_e2e_designer::test_write_cases_to_repo_creates_files_and_manifest",
            "test_e2e_full_flow::test_full_flow_dialog_and_memory",
        ]),
        ("重构用例处置", [
            "test_incremental::test_analyze_test_impact_refactor_fix_selector",
            "test_e2e_designer::test_write_cases_to_repo_preserves_expected_broken_status",
            "test_incremental::test_e2e_designer_regression_mode_preserves_cases",
        ]),
    ],
    "memory-system": [
        ("长期用户级记忆跨应用生效", [
            "test_memory::test_servicer_stream_graph_injects_user_preferences_as_constraints",
            "test_memory::test_constraints_consumed_in_prompts_and_dispatch",
            "test_memory::test_brainstorm_profile_seeding_injects_preferences",
        ]),
        ("worker 无权读写记忆", [
            "test_spec_traceability::test_workers_have_no_memory_access",
        ]),
        ("记忆目录生成", [
            "test_memory::test_write_helpers_create_full_structure",
            "test_memory::test_project_root_persistent_data_dir",
        ]),
        ("架构 Spec 复用", [
            "test_memory::test_persist_design_pass_writes_spec_and_md",
            "test_architecture_spec::test_phase2_spec_written_to_memory_on_pass",
        ]),
        ("节点完成后落盘", [
            "test_memory::test_persist_analysis_writes_requirements",
            "test_memory::test_persist_code_writes_state_and_contracts",
            "test_e2e_full_flow::test_full_flow_dialog_and_memory",
        ]),
        ("问题修复留痕", [
            "test_memory::test_record_problem_writes_all_layers",
            "test_recovery::test_classification_writes_problems_jsonl",
            "test_failure_injection::test_repeated_failure_red_line_rescue_then_reset_pass",
        ]),
        ("崩溃后恢复", [
            "test_memory::test_load_app_state_reconstructs_completed_stages",
            "test_memory::test_load_app_state_mid_stage_crash_not_restored",
            "test_memory::test_restored_state_skips_completed_stages",
            "test_crash_recovery_drill::test_crash_mid_code_resume_completes_pipeline",
        ]),
        ("增量需求 diff", [
            "test_incremental::test_graph_incremental_diff_confirm_pauses",
            "test_incremental::test_classify_diff_added_removed_and_removed_ids",
        ]),
        ("manifest 用户确认", [
            "test_incremental::test_graph_incremental_manifest_step_after_diff",
            "test_incremental::test_generate_manifest_schema_and_diagnoser_compat",
        ]),
        ("重构类型影响用例处置", [
            "test_incremental::test_analyze_test_impact_refactor_fix_selector",
        ]),
        ("处置清单呈现", [
            "test_incremental::test_graph_incremental_disposition_step",
            "test_incremental::test_analyze_test_impact_dispositions",
        ]),
        ("active 用例失败", [
            "test_incremental::test_regression_accounting_semantics",
            "test_incremental::test_regression_accounting_maps_diag_expected_broken_to_expected",
            "test_manager_gate::test_runner_resume_after_e2e_diagnoser_flow",
        ]),
    ],
    "problem-recovery": [
        ("跑偏分类", [
            "test_recovery::TestClassifyLLM::test_llm_classifies_design_missing_drift",
            "test_recovery::TestClassifyLLM::test_llm_fail_safe_heuristic_low",
        ]),
        ("格式非法分类", [
            "test_recovery::test_format_invalid_design_spec_fields",
            "test_recovery::test_format_invalid_code_empty",
        ]),
        ("重派", [
            "test_recovery::TestChooseStrategy::test_redispatch_first_attempt_compile",
            "test_recovery::TestEndToEndRedLine::test_design_red_line_continue_autonomous_resets_and_passes",
        ]),
        ("拆分", [
            "test_recovery::TestChooseStrategy::test_split_second_attempt_compile",
            "test_recovery::test_i4_split_instruction_drives_debugger",
        ]),
        ("回退", [
            "test_recovery::TestChooseStrategy::test_drift_design_redispatch_then_rollback",
            "test_recovery::TestChooseStrategy::test_e2e_drift_rollbacks_code",
            "test_manager_gate::test_gate_routes_e2e_failed_results_to_code_rollback",
        ]),
        ("上报", [
            "test_recovery::TestChooseStrategy::test_no_convergence_escalates",
            "test_recovery::TestChooseStrategy::test_red_line_escalates",
            "test_recovery::test_e2e_loop_break_carries_classification",
        ]),
        ("两轮后汇报", [
            "test_recovery::TestRedLineAttempts::test_bump_and_hit_threshold",
            "test_recovery::test_manual_gate_red_line_emits_rescue_card",
            "test_failure_injection::test_repeated_failure_red_line_rescue_then_reset_pass",
        ]),
        ("范围变更需确认", [
            "test_recovery::test_manual_gate_scope_change_emits_confirm_card",
            "test_recovery::test_consume_scope_confirmation",
            "test_recovery::test_scope_rejection_on_regen_resume",
            "test_feedback::test_run_consumes_scope_change_halts_with_confirm_card",
        ]),
        ("单节点回退超限", [
            "test_recovery::test_gate_escalates_on_loop_control_blocked",
        ]),
        ("无改进熔断", [
            "test_recovery::test_gate_escalates_on_no_improvement",
            "test_verifier_debugger::TestGraphFixRoundLoop::test_fix_round_no_progress_breaks_and_gate_redoes",
        ]),
        ("问题记录写入", [
            "test_recovery::test_classification_writes_problems_jsonl",
            "test_memory::test_record_problem_writes_all_layers",
            "test_recovery::test_resolve_outcomes_and_success_counting",
        ]),
        ("历史策略复用", [
            "test_recovery::test_retrieval_suggested_fix",
            "test_recovery::test_debugger_prompt_has_history",
        ]),
    ],
    "code-feedback-loop": [
        ("反馈成功接收", [
            "test_feedback::TestReportUserFeedbackServicer::test_report_user_feedback_disposes",
            "test_feedback::TestReportUserFeedbackServicer::test_report_then_run_consumes_end_to_end",
        ]),
        ("无效 generation_id", [
            "test_feedback::TestReportUserFeedbackServicer::test_report_user_feedback_no_runner_aborts_not_found",
        ]),
        ("遗漏类反馈", [
            "test_feedback::TestDisposeUserFeedback::test_omission_pends_redispatch_and_records_problem",
            "test_feedback::test_run_consumes_redispatch_and_emits_card",
        ]),
        ("范围变更类反馈", [
            "test_feedback::test_run_consumes_scope_change_halts_with_confirm_card",
            "test_feedback::test_scope_confirm_then_rerun_carries_approved_scope",
        ]),
        ("卡片默认折叠", [
            "test_dialog::test_feedback_disposition_card_collapsed",
            "test_feedback::test_run_consumes_redispatch_and_emits_card",
        ]),
    ],
    "compile-feedback": [
        ("错误写入 generation 状态", [
            "test_verifier_debugger::TestRuntimeFeedbackServicer::test_report_runtime_feedback_stores_on_runner",
            "test_verifier_debugger::test_graph_runner_reports_to_registry",
        ]),
        ("编译工具返回真实错误", [
            "test_verifier_debugger::TestVerifierL1::test_l1_fails_on_frontend_compile_errors",
            "test_failure_injection::test_compile_error_verifier_fail_debugger_fix_pass",
        ]),
        ("无上报错误时编译通过", [
            "test_verifier_debugger::TestVerifierL1::test_l1_passes_without_errors",
        ]),
        ("console 错误上报", [
            "test_verifier_debugger::TestRuntimeFeedbackServicer::test_report_runtime_feedback_stores_on_runner",
            "test_verifier_debugger::TestVerifierL3::test_l3_fails_on_reported_runtime_errors",
        ]),
    ],
}

# 文档化的场景总数 (spec 解析结果漂移守卫)。
DOCUMENTED_SCENARIO_COUNT = 86

# 记忆层允许访问的模块 (Manager 层)。
_MEMORY_LAYER_MODULES = frozenset({
    "servicer", "graph", "manager", "memory", "memory_db",
    "recovery", "feedback", "brainstorm", "incremental",
})
# worker 模块 — 不得读写记忆 (6.2)。(executor_task 位于 nodes.py。)
_WORKER_MODULES = frozenset({
    "nodes", "planner", "verifier", "debugger", "tester",
    "e2e_designer", "e2e_diagnoser", "tier", "context_manager",
    "tools", "state", "dialog", "harness", "spec_schema",
})


def _spec_dirs() -> list[str]:
    """9 个 spec 目录名 (specs/ 下的目录清单)。"""
    here = Path(__file__).resolve()
    root = here
    while root != root.parent and not (root / "openspec").is_dir():
        root = root.parent
    specs = root / "openspec" / "changes" / "agent-orchestration-upgrade" / "specs"
    assert specs.is_dir(), f"specs dir not found: {specs}"
    return sorted(d.name for d in specs.iterdir() if d.is_dir() and (d / "spec.md").is_file())


def _parse_scenarios() -> dict[str, list[str]]:
    """解析每个 spec 的 ``#### Scenario: <标题>`` 行 → {spec_dir: [标题]}。"""
    here = Path(__file__).resolve()
    root = here
    while root != root.parent and not (root / "openspec").is_dir():
        root = root.parent
    specs = root / "openspec" / "changes" / "agent-orchestration-upgrade" / "specs"
    out: dict[str, list[str]] = {}
    pattern = re.compile(r"^#### Scenario:\s*(.+?)\s*$", re.MULTILINE)
    for spec_dir in _spec_dirs():
        text = (specs / spec_dir / "spec.md").read_text(encoding="utf-8")
        out[spec_dir] = [m.group(1).strip() for m in pattern.finditer(text)]
    return out


def _load_test_modules() -> dict[str, object]:
    """Import the tests package modules referenced by the matrix."""
    import sys

    here = _TESTS_DIR.resolve()
    if str(here.parent) not in sys.path:
        sys.path.insert(0, str(here.parent))
    mods: dict[str, object] = {}
    for refs in MATRIX.values():
        for _title, covering in refs:
            for ref in covering:
                mod_name = ref.split("::")[0]
                if mod_name in mods:
                    continue
                try:
                    mods[mod_name] = importlib.import_module(f"tests.{mod_name}")
                except ImportError:
                    mods[mod_name] = importlib.import_module(mod_name)
    return mods


def _resolve_ref(ref: str, mods: dict[str, object]) -> bool:
    """Resolve "module::[class::]name" — 允许省略类名: 模块级函数不存在时
    回退到类方法 (矩阵按函数名引用, 类归属可漂移)。"""
    import inspect

    parts = ref.split("::")
    mod = mods.get(parts[0])
    if mod is None:
        return False
    if len(parts) == 2:
        obj = getattr(mod, parts[1], None)
        if callable(obj) or inspect.isclass(obj):
            return True
        # 类方法回退: 在模块的测试类中查找同名方法。
        for cls_name in dir(mod):
            cls = getattr(mod, cls_name)
            if inspect.isclass(cls) and getattr(cls, parts[1], None) is not None:
                return True
        return False
    obj = mod
    for part in parts[1:]:
        obj = getattr(obj, part, None)
        if obj is None:
            return False
    return callable(obj) or inspect.isclass(obj)


def inspect_is_class(obj: object) -> bool:
    import inspect

    return inspect.isclass(obj)


def test_every_scenario_mapped_and_coverable():
    """每个 spec 场景都有矩阵条目, 且映射的测试真实存在。"""
    parsed = _parse_scenarios()
    mods = _load_test_modules()

    parsed_total = sum(len(v) for v in parsed.values())
    assert parsed_total == DOCUMENTED_SCENARIO_COUNT, (
        f"spec 场景总数漂移: 解析到 {parsed_total}, 文档化 {DOCUMENTED_SCENARIO_COUNT}。"
        "若 spec 变更请同步 spec-traceability.md 与 DOCUMENTED_SCENARIO_COUNT。"
    )

    # 1) 每个解析出的场景都有矩阵条目
    missing: list[str] = []
    matrix_titles = {t for refs in MATRIX.values() for t, _ in refs}
    for spec_dir, titles in parsed.items():
        for title in titles:
            if title not in matrix_titles:
                missing.append(f"{spec_dir}: {title}")
    assert not missing, f"以下场景无矩阵条目 (未覆盖): {missing}"

    # 2) 矩阵条目都在 spec 中存在 (无孤儿行)
    parsed_flat = {t for titles in parsed.values() for t in titles}
    orphans = [f"{spec_dir}: {title}" for spec_dir, refs in MATRIX.items()
               for title, _ in refs if title not in parsed_flat]
    assert not orphans, f"矩阵存在孤儿行 (spec 中无对应场景): {orphans}"

    # 3) 每个矩阵条目的映射测试函数真实存在
    broken: list[str] = []
    for spec_dir, refs in MATRIX.items():
        for title, covering in refs:
            for ref in covering:
                if not _resolve_ref(ref, mods):
                    broken.append(f"{spec_dir}:{title} → {ref}")
    assert not broken, f"以下映射的测试不存在 (空验证): {broken}"

    # 4) 每个场景至少一个覆盖测试
    empty = [f"{spec_dir}: {title}" for spec_dir, refs in MATRIX.items()
             for title, covering in refs if not covering]
    assert not empty, f"以下场景无覆盖测试: {empty}"


def test_matrix_spec_dirs_match_disk():
    """矩阵的 spec 目录与磁盘上的 9 个 spec 目录一致。"""
    assert sorted(MATRIX) == _spec_dirs()


def test_matrix_matches_traceability_doc():
    """矩阵与 spec-traceability.md 文档一致 (文档漂移守卫)。

    除场景标题与总数外, 文档中每个测试引用 (``模块[.py]::[类::]函数`` 反引号
    内) 都必须真实存在 — 文档的每条可执行验证不可悬空。
    """
    here = Path(__file__).resolve()
    root = here
    while root != root.parent and not (root / "openspec").is_dir():
        root = root.parent
    doc = root / "openspec" / "changes" / "agent-orchestration-upgrade" / "spec-traceability.md"
    assert doc.is_file(), "spec-traceability.md 缺失"
    text = doc.read_text(encoding="utf-8")
    for title in {t for refs in MATRIX.values() for t, _ in refs}:
        assert title in text, f"spec-traceability.md 缺少场景条目: {title}"
    assert f"| {DOCUMENTED_SCENARIO_COUNT} |" in text

    # 文档中的测试引用全部可解析 (review nit: 场景级引用不可悬空)。
    mods = _load_test_modules()
    unresolved: list[str] = []
    for ref in re.findall(r"`([^`]*\.py::[^`]+)`", text):
        norm = ref.replace("\\", "/").split("/")[-1]   # 去掉路径前缀
        parts = norm.split("::")
        parts[0] = parts[0].removesuffix(".py")        # 模块名去掉 .py
        if not _resolve_ref("::".join(parts), mods):
            unresolved.append(ref)
    assert not unresolved, f"spec-traceability.md 引用的测试不存在: {unresolved}"


def test_workers_have_no_memory_access():
    """6.2: worker 模块无权读写记忆 — 不 import memory_db / memory 写层。

    记忆 (memory_db SQLite / .ai-memory 写透) 只存在于 Manager 层模块;
    worker 模块仅允许使用 ``memory.project_root_for`` 之类的路径解析辅助
    (非记忆读写), 不得触碰记忆层。
    """
    here = Path(__file__).resolve()
    root = here
    while root != root.parent and not (root / "app").is_dir():
        root = root.parent
    gen = root / "app" / "services" / "generation"

    for mod in sorted(_WORKER_MODULES):
        base = gen / mod
        files: list[Path] = []
        if base.is_dir():
            files = [p for p in base.rglob("*.py") if "__pycache__" not in str(p)]
        elif base.with_suffix(".py").is_file():
            files = [base.with_suffix(".py")]
        assert files, f"模块文件未找到: {mod}"
        for f in files:
            src = f.read_text(encoding="utf-8")
            assert "memory_db" not in src, (
                f"worker 模块 {f.name} 不得读写记忆 (memory_db): 违反 6.2 场景"
            )
            # 写层辅助 (write_* / record_problem / persist_*) 也不得进入 worker。
            for banned in ("persist_stage_artifacts", "record_problem", "write_state", "append_problem"):
                assert banned not in src, (
                    f"worker 模块 {f.name} 不得调用记忆写层 ({banned}): 违反 6.2 场景"
                )
