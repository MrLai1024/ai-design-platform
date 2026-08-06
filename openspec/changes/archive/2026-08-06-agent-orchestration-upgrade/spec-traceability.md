# Spec Traceability Matrix — agent-orchestration-upgrade

Task 11.1: 按 9 个 spec 的场景逐条核对实现, 每条场景至少一个可执行验证。

- Spec 文件: `openspec/changes/agent-orchestration-upgrade/specs/<spec>/spec.md`
- 测试根: `ai-design-platform-server/ai-service/tests/` (pytest, `PYTHONPATH=app python -m pytest -q`)
- 程序化守卫: `tests/test_spec_traceability.py` — 解析 9 个 spec 的全部
  `#### Scenario` 行, 断言矩阵表覆盖每个场景且映射的测试函数存在。

## 覆盖统计

| 维度 | 数量 |
|---|---|
| 场景总数 (9 spec, `#### Scenario` 行) | 86 |
| 已有测试覆盖 | 83 |
| 本次新增覆盖 (11.2-11.5 演练 + 缺口修复) | 3 |
| 已知限制 (文档化, 不扩范围) | 2 |

## 1. coordinator-agent (`coordinator-agent/spec.md`, 6 需求 / 12 场景)

| # | 需求 | 场景 | 覆盖验证 (tests/) |
|---|---|---|---|
| 1.1 | Manager 是唯一与用户对话的 Agent | 节点完成时 Manager 发言 | `test_manager_gate.py::test_gate_manual_stage_emits_verdict`; `test_manager_gate.py::test_manager_verdict_events_emit_cards`; `test_dialog.py::test_summary_card_event` / `test_verdict_card_event_pass_and_fail`; 11.2 全流程对话框消息序列 |
| 1.2 | 同上 | worker 不直接发言 | `test_e2e_full_flow.py::test_full_flow_dialog_and_memory` (断言 worker 产物事件如 doc_chunk 不出 manager_message); `test_dialog.py::test_card_events_share_single_event_type_shape` |
| 1.3 | 任务分发携带验收标准 | 分发包含验收标准 | `test_implementation_tier.py::test_build_code_dispatch_contract`; `test_memory.py::test_constraints_consumed_in_prompts_and_dispatch`; 11.2 断言 state.dispatch_contract 含 acceptance_criteria |
| 1.4 | 同上 | 工具边界约束 | 11.2 断言 dispatch_contract.tool_bounds 存在; `test_manager_gate.py` dispatch 契约形状 (servicer 初始化, `test_generation_servicer.py`) |
| 1.5 | 分层把关 | L1 硬规则失败 | `test_architecture_spec.py::test_l1_failure_skips_l2_and_evidences_redo`; `test_manager_gate.py::test_run_l1_checks_analysis` / `test_manager_gate.py::test_run_l1_checks_design` / `test_manager_gate.py::test_run_l1_checks_code` / `test_manager_gate.py::test_run_l1_checks_e2e`; `test_spec_schema.py::test_validate_spec_missing_field` |
| 1.6 | 同上 | L3 发现跑偏 | `test_recovery.py::test_e2e_drift_rollbacks_code`; `test_recovery.py::TestClassifyLLM::test_llm_classifies_design_missing_drift`; `test_architecture_spec.py::test_evaluate_stage_l2_design_missing_surfaces_in_verdict_and_diagnosis`; 11.3(c) 漂移注入演练 |
| 1.7 | 同上 | 把关通过 | `test_manager_gate.py::test_gate_manual_stage_emits_verdict` (pass 分支); `test_architecture_spec.py::test_phase2_dual_product_and_gate_pass` |
| 1.8 | 把关时机为节点完成后、用户确认前 | 把关先行于确认 | `test_manager_gate.py::test_runner_phase4_announce_message_matches_verdict`; `test_recovery.py::test_i3_analysis_redo_clears_and_feeds_back` (redo 后不展示下一步, 先恢复) |
| 1.9 | 用户输入意图路由 | 澄清回答路由 | `test_brainstorm.py::test_answer_via_item_id_and_assumed_marking`; `test_answer_supersedes_assumption`; `test_answering_different_answer_marks_conflict` |
| 1.10 | 同上 | 产出反馈路由 | `test_brainstorm.py::test_proposal_phase_free_text_is_feedback_not_answer`; `test_feedback.py::TestDisposeUserFeedback::test_omission_pends_redispatch_and_records_problem`; `test_recovery.py::test_feedback_text_carries_classification` |
| 1.11 | 同上 | 流程指令路由 | `test_dialog.py::test_classify_intent_all_vocab` (proceed); `test_brainstorm.py::test_coverage_insufficient_does_not_converge` ("可以开始了吗" 处理) |
| 1.12 | 节点确认机制 | 产物区确认与对话框叙事并存 | `test_manager_gate.py::test_runner_phase4_gate_flow` (human_confirm_required + 卡片并存); `test_gate_manual_stage_emits_verdict` |

## 2. brainstorm-clarification (`brainstorm-clarification/spec.md`, 6 需求 / 9 场景)

| # | 需求 | 场景 | 覆盖验证 |
|---|---|---|---|
| 2.1 | 议程驱动的澄清 | 议程项维护 | `test_brainstorm.py::test_agenda_item_to_dict`; `test_answer_via_item_id_and_assumed_marking` |
| 2.2 | 同上 | 用户未答项标记假设 | `test_brainstorm.py::test_answer_via_item_id_and_assumed_marking` (a3 assumed); `test_answer_supersedes_assumption`; 假设进入 PRD: `test_analysis_prd_prompt_mentions_assumptions_section` |
| 2.3 | 首轮需求画像 | 首轮产出画像 | `test_brainstorm.py::test_first_turn_produces_profile_card_no_questions` |
| 2.4 | 问题按影响排序提问 | 关键路径问题优先 | `test_brainstorm.py::test_question_round_asks_by_impact_design_first` |
| 2.5 | 候选方案对比 | 方案选择 | `test_brainstorm.py::test_proposal_choice_records_decision_and_offers_confirm`; `test_proposal_regenerate` |
| 2.6 | 同上 | 方案对比缺席时不得收敛 | `test_brainstorm.py::test_confirm_request_blocker_proposal_when_coverage_met` (blocker=proposal) |
| 2.7 | 双因子收敛 | 覆盖不足不收敛 | `test_brainstorm.py::test_coverage_insufficient_does_not_converge`; `test_empty_agenda_coverage_zero_does_not_converge` |
| 2.8 | 同上 | 覆盖达标且用户确认 | `test_brainstorm.py::test_full_lifecycle_to_convergence` (r5/r6); `test_short_pure_confirm_converges`; `test_confirm_card_option_converges_even_with_pending` |
| 2.9 | 澄清产出物 | 产出物完整 | `test_brainstorm.py::test_full_lifecycle_to_convergence` (结构化需求+决策日志+假设清单); `test_stream_graph_loads_brainstorm_session_products` (会话产物进 state); `test_graph_phase1_prd_consumes_clarification_products` |

## 3. architecture-spec (`architecture-spec/spec.md`, 6 需求 / 8 场景)

| # | 需求 | 场景 | 覆盖验证 |
|---|---|---|---|
| 3.1 | 方案设计节点输出双产物 | 双产物输出 | `test_architecture_spec.py::test_phase2_dual_product_and_gate_pass`; `test_generate_spec_valid_first_shot` |
| 3.2 | 架构 Spec 字段完整 | 字段缺失判不通过 | `test_spec_schema.py::test_validate_spec_missing_field` / `test_validate_spec_reports_all_missing_fields`; `test_architecture_spec.py::test_l1_catches_missing_spec_fields` |
| 3.3 | 同上 | 字段完整判通过 | `test_spec_schema.py::test_validate_spec_full_valid`; `test_harness_spec_check_deterministic` |
| 3.4 | Spec 与 PRD 一致性 | 功能点遗漏 | `test_architecture_spec.py::test_l2_parses_missing_list`; `test_phase2_l2_failure_gate_fails_with_missing_list`; `test_evaluate_stage_l2_design_missing_surfaces_in_verdict_and_diagnosis` |
| 3.5 | 同上 | 功能点全落地 | `test_architecture_spec.py::test_l2_pass`; `test_phase2_dual_product_and_gate_pass` (L2 通过分支) |
| 3.6 | Spec 作为功能实现的输入 | Planner 消费 Spec | `test_implementation_tier.py::TestPlannerSpecDriven::test_user_prompt_built_from_spec`; `test_system_prompt_no_hardcoded_heuristics`; `test_fallback_from_spec_no_bootstrap_hardcode` |
| 3.7 | Spec 作为验证基准 | 目录与 Spec 不符 | `test_verifier_debugger.py::TestVerifierL2::test_contract_task_with_missing_files_fails` (Planner 依 Spec directory_tree 生成契约文件清单, 缺失目录 → missing_file 证据); `test_l2_dep_pair_violation` |
| 3.8 | 决策记录入 Spec | 用户选择写入决策 | `test_architecture_spec.py::test_generate_spec_consumes_clarification_products` (决策进 Spec prompt); `test_spec_schema.py::test_write_spec_to_memory_writes_file` (decisions 随 Spec 持久化); `test_memory.py::test_brainstorm_proposal_choice_upserts_preference` |

## 4. function-implementation (`function-implementation/spec.md`, 6 需求 / 11 场景)

| # | 需求 | 场景 | 覆盖验证 |
|---|---|---|---|
| 4.1 | 复杂度分档 | S 档最小配置 | `test_implementation_tier.py::TestAssessComplexity::test_s_simple_form_spec` / `test_s_with_state_framework_but_no_stores`; `test_build_code_dispatch_contract` (roles=planner,executor) |
| 4.2 | 同上 | L 档完整配置 | `test_implementation_tier.py::test_l_permissions` / `test_l_api_layer` / `test_l_multi_module`; `test_build_code_dispatch_contract` (roles 含 debugger/tester); `test_tester_parallel.py::TestFullLLoop::test_tester_failure_debugger_fix_retest_pass` |
| 4.3 | Planner 基于 Spec 拆解 | DAG 与 Spec 对齐 | `test_implementation_tier.py::test_user_prompt_built_from_spec` (directory_tree/data_model/component_tree 全量进 prompt); 11.2 全流程: planner DAG 任务文件源自 Spec 目录 |
| 4.4 | Executor 验收驱动 | 契约验收 | `test_implementation_tier.py::TestExecutorAcceptance` / `TestVerifyContractHardening`; `test_verifier_debugger.py::TestVerifierL2::test_l2_detects_missing_export` (验收失败→失败处理) |
| 4.5 | Verifier 四层验证信号 | L1 编译失败 | `test_verifier_debugger.py::TestVerifierL1::test_l1_fails_on_frontend_compile_errors` (file/line/message 证据); 11.3(a) 编译失败注入演练 |
| 4.6 | 同上 | L3 运行时失败 | `test_verifier_debugger.py::TestVerifierL3::test_l3_fails_on_reported_runtime_errors`; `test_report_runtime_feedback_stores_on_runner` |
| 4.7 | 同上 | 四层全部通过 | `test_verifier_debugger.py::TestVerifierResultShape::test_result_shape` (l1-l4+hooks 全通过 = passed); 11.2 全流程 verifier passed |
| 4.8 | Debugger 根因修复 | 契约违约修复 | `test_verifier_debugger.py::TestDebuggerFixRoundIntegration::test_fix_round_contract_violation_repairs_and_passes`; `TestExecutorFixContext::test_fix_instructions_threaded_into_prompt` |
| 4.9 | 同上 | 无进展检测 | `test_verifier_debugger.py::TestDebuggerNoProgress::test_same_signature_is_no_progress`; `TestGraphFixRoundLoop::test_fix_round_no_progress_breaks_and_gate_redoes`; 11.3(b) 同证据失败注入 |
| 4.10 | 测试钩子埋点 | 关键元素埋点 | `test_verifier_debugger.py::TestScanHooks::test_flags_button_without_testid` / `test_passes_with_testid` / `test_flags_interactive_element_components` |
| 4.11 | 同上 | 钩子作为验收项 | `test_verifier_debugger.py::TestVerifierHooks::test_hooks_fail_and_evidence_carries_list`; `test_fix_round_hooks_violation_repairs_and_passes` (闭环); `test_executor_prompt_mandates_testid` |

## 5. e2e-verification (`e2e-verification/spec.md`, 7 需求 / 13 场景)

| # | 需求 | 场景 | 覆盖验证 |
|---|---|---|---|
| 5.1 | 测试用例覆盖矩阵 | 覆盖矩阵门禁 | `test_e2e_designer.py::test_designer_coverage_gate_marks_gap`; `test_designer_rb_only_rows_flagged_in_coverage` |
| 5.2 | 同上 | 全需求点覆盖 | `test_e2e_designer.py::test_designer_valid_cases_coverage_passes` |
| 5.3 | 用例结构化 DSL | DSL 用例生成 | `test_e2e_designer.py::test_validate_case_ok`; `test_designer_valid_cases_coverage_passes` (cases 结构); `test_e2e_designer.py::test_selector_priority_in_prompt` |
| 5.4 | 同上 | 非法 DSL 拒绝执行 | `test_e2e_designer.py::test_validate_case_rejects_bad_schema` / `test_validate_case_rejects_bad_action_and_by`; `test_designer_invalid_cases_repair_then_drop` (触发重生成) |
| 5.5 | 选择器优先测试钩子 | 优先 testid | `test_e2e_designer.py::test_selector_priority_in_prompt` |
| 5.6 | 用例确认环节 | 用户确认执行 | `test_manager_gate.py::test_runner_resume_gate_worker_gate_cycle` (resume e2e_confirmed → e2e_execute_start, 未确认绝不自动执行); `test_gate_routes_e2e_no_results_to_pause_after_confirmed` |
| 5.7 | 执行引擎增强 | 失败证据收集 | `test_e2e_diagnoser.py::test_failing_step_parsed_from_error_text_for_later_steps` (证据进入诊断); `test_manager_gate.py::test_resume_after_e2e_rollback_announces_paused_worker` (DOM 快照证据); 前端 `ai-design-platform-web` runner 测试 (console/网络监听, 见 6.3/6.4 前端单测) |
| 5.8 | 同上 | 等待条件 | 前端执行引擎 (MutationObserver 轮询) 单测: `ai-design-platform-web/packages/*` vitest (非 skipif-gated 部分); 后端侧执行由前端 runner 驱动 (11.2 断言 e2e_execute_start 交接) |
| 5.9 | 失败三方诊断 | 预期失效 | `test_e2e_diagnoser.py::test_expected_broken_when_manifest_declares_change`; `test_manager_gate.py::test_runner_resume_after_e2e_diagnoser_flow` (不触发代码回退); `test_gate_all_expected_broken_routes_to_end` |
| 5.10 | 同上 | 真实回归 | `test_e2e_diagnoser.py::test_assertion_mismatch_without_manifest_is_real_regression`; `test_manager_gate.py::test_gate_routes_e2e_failed_results_to_code_rollback`; `test_resume_after_e2e_rollback_announces_paused_worker` |
| 5.11 | 复杂用例标注 | 复杂用例跳过 | `test_e2e_designer.py::test_designer_requires_browser_annotation_survives`; `test_manager_gate.py::test_runner_resume_after_e2e_skipped_cases_pass`; `test_run_l1_checks_e2e_skips_requires_browser` |
| 5.12 | 用例入库版本化 | 用例写入仓库 | `test_e2e_designer.py::test_write_cases_to_repo_creates_files_and_manifest`; 11.2 全流程断言 e2e/cases/*.json + manifest.json 落盘 |
| 5.13 | 同上 | 重构用例处置 | `test_incremental.py::test_analyze_test_impact_refactor_fix_selector`; `test_e2e_designer.py::test_write_cases_to_repo_preserves_expected_broken_status`; `test_incremental.py::test_apply_dispositions_updates_manifest_statuses`; `test_e2e_designer_regression_mode_preserves_cases` |

## 6. memory-system (`memory-system/spec.md`, 6 需求 / 12 场景)

| # | 需求 | 场景 | 覆盖验证 |
|---|---|---|---|
| 6.1 | 四层记忆 | 长期用户级记忆跨应用生效 | `test_memory.py::test_servicer_stream_graph_injects_user_preferences_as_constraints`; `test_constraints_consumed_in_prompts_and_dispatch`; `test_brainstorm_session_user_id`; `test_brainstorm_profile_seeding_injects_preferences` |
| 6.2 | 同上 | worker 无权读写记忆 | `test_spec_traceability.py::test_workers_have_no_memory_access` (nodes/planner/executor/verifier/tester 模块不 import memory_db; worker 仅经 dispatch 上下文取信息) |
| 6.3 | 应用记忆目录结构 | 记忆目录生成 | `test_memory.py::test_write_helpers_create_full_structure` (index.json/spec/state/changes/problems.jsonl); `test_project_root_persistent_data_dir` |
| 6.4 | 同上 | 架构 Spec 复用 | `test_memory.py::test_persist_design_pass_writes_spec_and_md`; `test_architecture_spec.py::test_phase2_spec_written_to_memory_on_pass` |
| 6.5 | 生成期持续写入 | 节点完成后落盘 | `test_memory.py::test_persist_analysis_writes_requirements`; `test_persist_code_writes_state_and_contracts`; 11.2 全流程断言三件套落盘 |
| 6.6 | 同上 | 问题修复留痕 | `test_memory.py::test_record_problem_writes_all_layers` (problems.jsonl + 中期/长期); `test_recovery.py::test_classification_writes_problems_jsonl`; 11.3(b) 断言 problems.jsonl 记录 |
| 6.7 | 崩溃恢复检查点 | 崩溃后恢复 | `test_memory.py::test_load_app_state_reconstructs_completed_stages` / `test_load_app_state_mid_stage_crash_not_restored` / `test_restored_state_skips_completed_stages`; `test_servicer_stream_graph_prefills_state_from_memory`; 11.5 代码节点中断后重启恢复演练 |
| 6.8 | 增量开发加载 | 增量需求 diff | `test_incremental.py::test_graph_incremental_diff_confirm_pauses`; `test_classify_diff_*` (新增/修改/删除); `test_load_incremental_context` (摘要+按需检索: `test_load_summary_and_section`) |
| 6.9 | 变更 manifest | manifest 用户确认 | `test_incremental.py::test_graph_incremental_manifest_step_after_diff` (确认前暂停, 草稿落 changes/); `test_generate_manifest_schema_and_diagnoser_compat` |
| 6.10 | 同上 | 重构类型影响用例处置 | `test_incremental.py::test_analyze_test_impact_refactor_fix_selector` (keep 必须回归通过 / fix-selector 修选择器) |
| 6.11 | 历史用例处置与回归对账 | 处置清单呈现 | `test_incremental.py::test_graph_incremental_disposition_step` (清单卡片 + 确认暂停); `test_analyze_test_impact_dispositions` |
| 6.12 | 同上 | active 用例失败 | `test_incremental.py::test_regression_accounting_semantics` (active 红=真回归); `test_regression_accounting_maps_diag_expected_broken_to_expected`; `test_manager_gate.py::test_runner_resume_after_e2e_diagnoser_flow` (真回归回退代码) |

## 7. problem-recovery (`problem-recovery/spec.md`, 5 需求 / 12 场景)

| # | 需求 | 场景 | 覆盖验证 |
|---|---|---|---|
| 7.1 | 失败分类 | 跑偏分类 | `test_recovery.py::TestClassifyLLM::test_llm_classifies_design_missing_drift`; `test_llm_fail_safe_heuristic_low` (启发式兜底) |
| 7.2 | 同上 | 格式非法分类 | `test_recovery.py::test_format_invalid_design_spec_fields`; `test_format_invalid_code_empty` |
| 7.3 | 恢复策略阶梯 | 重派 | `test_recovery.py::TestChooseStrategy::test_redispatch_first_attempt_compile`; `test_drift_design_redispatch_then_rollback` (带反馈重派, 不重建全流程: `test_recovery.py::TestEndToEndRedLine` 第 4 轮带反馈重跑) |
| 7.4 | 同上 | 拆分 | `test_recovery.py::test_split_second_attempt_compile`; `test_i4_split_instruction_drives_debugger` |
| 7.5 | 同上 | 回退 | `test_recovery.py::test_drift_design_redispatch_then_rollback` (rollback 分支); `test_e2e_drift_rollbacks_code`; `test_gate_routes_e2e_failed_results_to_code_rollback` |
| 7.6 | 同上 | 上报 | `test_recovery.py::test_no_convergence_escalates`; `test_red_line_escalates`; `test_e2e_loop_break_carries_classification` |
| 7.7 | 自主闭环红线 | 两轮后汇报 | `test_recovery.py::TestRedLineAttempts::test_bump_and_hit_threshold` (3 轮红线); `test_manual_gate_red_line_emits_rescue_card` (求援卡+继续自主/转人工); 11.3(b) 代码节点红线演练 |
| 7.8 | 同上 | 范围变更需确认 | `test_recovery.py::test_manual_gate_scope_change_emits_confirm_card`; `test_consume_scope_confirmation`; `test_scope_rejection_on_regen_resume`; `test_scope_approval_enters_design_feedback`; `test_feedback.py::test_run_consumes_scope_change_halts_with_confirm_card` |
| 7.9 | 回退次数控制 | 单节点回退超限 | `test_recovery.py::test_gate_escalates_on_loop_control_blocked` (3 次转求援) |
| 7.10 | 同上 | 无改进熔断 | `test_recovery.py::test_gate_escalates_on_no_improvement` (同哈希连续回退熔断) |
| 7.11 | 问题记录持久化 | 问题记录写入 | `test_recovery.py::test_classification_writes_problems_jsonl` (问题/分类/根因/修复/结果); `test_record_problem_writes_all_layers`; `test_resolve_outcomes_and_success_counting` (闭环 resolved) |
| 7.12 | 同上 | 历史策略复用 | `test_recovery.py::test_retrieval_suggested_fix`; `test_debugger_prompt_has_history`; `test_history_block_empty_without_history` |

## 8. code-feedback-loop (`code-feedback-loop/spec.md`, 3 需求 / 5 场景)

| # | 需求 | 场景 | 覆盖验证 |
|---|---|---|---|
| 8.1 | 反馈端点接收 | 反馈成功接收 | `test_feedback.py::TestReportUserFeedbackServicer::test_report_user_feedback_disposes` / `test_report_then_run_consumes_end_to_end` (RPC→问题记录→Manager 恢复决策); 网关 HTTP 层 `gateway/` (go test) |
| 8.2 | 同上 | 无效 generation_id | `test_feedback.py::test_report_user_feedback_no_runner_aborts_not_found` (404 等价); `test_servicer_stream_guard` NOT_FOUND 语义 |
| 8.3 | Manager 处置用户反馈 | 遗漏类反馈 | `test_feedback.py::TestDisposeUserFeedback::test_omission_pends_redispatch_and_records_problem`; `test_run_consumes_redispatch_and_emits_card` (重派指令进 DAG) |
| 8.4 | 同上 | 范围变更类反馈 | `test_feedback.py::test_run_consumes_scope_change_halts_with_confirm_card` (confirm_card 请求确认, 确认后更新需求继续); `test_scope_confirm_then_rerun_carries_approved_scope` |
| 8.5 | 反馈处置结果卡片 | 卡片默认折叠 | `test_dialog.py::test_feedback_disposition_card_collapsed` (feedback_card 默认折叠标记); `test_feedback.py::test_run_consumes_redispatch_and_emits_card` (首帧处置卡) |

## 9. compile-feedback (`compile-feedback/spec.md`, 3 需求 / 4 场景)

| # | 需求 | 场景 | 覆盖验证 |
|---|---|---|---|
| 9.1 | 后端接收并暂存编译错误 | 错误写入 generation 状态 | `test_verifier_debugger.py::TestRuntimeFeedbackServicer::test_report_runtime_feedback_stores_on_runner` (上报→runner registry); `test_graph_runner_reports_to_registry` (compile 同通道) |
| 9.2 | Verifier 消费真实编译错误 | 编译工具返回真实错误 | `test_verifier_debugger.py::TestVerifierL1::test_l1_fails_on_frontend_compile_errors` (file/line/message 证据进 Debugger); 11.3(a) 编译失败→修复闭环 |
| 9.3 | 同上 | 无上报错误时编译通过 | `test_verifier_debugger.py::test_l1_passes_without_errors` (通过后继续 L2) |
| 9.4 | 运行时错误上报 | console 错误上报 | `test_verifier_debugger.py::TestRuntimeFeedbackServicer::test_report_runtime_feedback_stores_on_runner` (console_error/uncaught + 关联 generation_id); `TestVerifierL3::test_l3_fails_on_reported_runtime_errors` (L3 证据) |

## 已知限制 (设计级, 文档化, 不扩范围)

1. **5.7/5.8 执行引擎增强 (失败证据收集 / 等待条件)** — 用例执行的
   console/网络监听、MutationObserver 等待与 DOM 快照/截图由前端 runner
   (`ai-design-platform-web`) 实现, 后端无等价物。后端侧覆盖 = 证据进入
   Diagnoser 分类 (`test_e2e_diagnoser.py` 证据消费) + 11.2 交接事件
   (e2e_execute_start); 前端 runner 行为由 web 侧 vitest 覆盖 (非
   skipif-gated 用例)。未在后端重实现浏览器执行 (一期设计决策, 见
   `e2e-verification/spec.md` 6.7 `requires_browser` 跳过语义)。
2. **6.2 worker 无权读写记忆** — 无独立"越权访问被拒"运行路径: 记忆读写
   通道 (memory_db) 只存在于 manager/graph/servicer 层, worker 模块
   (nodes/planner/executor/verifier/tester/e2e_*) 不导入 memory_db。
   以 `test_spec_traceability.py::test_workers_have_no_memory_access`
   的静态断言代替拒绝路径测试。

## 缺口修复记录 (本次)

| 缺口 | 修复 |
|---|---|
| 8.5 反馈处置卡片默认折叠 — dialog 层无默认折叠断言 | `test_dialog.py` 新增 `test_feedback_disposition_card_collapsed` |
| 6.2 worker 无权读写记忆 — 无验证 | `test_spec_traceability.py::test_workers_have_no_memory_access` 静态断言 |
| 系统级场景 (对话框消息完整性 / 崩溃恢复续跑 / 失败注入闭环) 无单测能覆盖 | 11.2-11.5 四个演练文件 |

## 11.2-11.5 演练文件

| 文件 | 覆盖任务 | 说明 |
|---|---|---|
| `tests/test_e2e_full_flow.py` | 11.2 | 头脑风暴→PRD→Spec→实现→E2E 全流程, 对话框卡片序列 + 记忆产物 + 最终裁决 END |
| `tests/test_failure_injection.py` | 11.3 | (a) 编译错→L1 失败→Debugger 修复→通过; (b) 同证据失败→无进展→求援红线→继续自主→通过; (c) 设计漏功能点→L2 重做→带反馈重生成→通过; (d) 中断→见 11.5 |
| `tests/test_incremental_drill.py` | 11.4 | 完整生成→增量入口 (diff→manifest→处置) →delta 流水线→存量文件不动→回归对账→changes/ 记录 |
| `tests/test_crash_recovery_drill.py` | 11.5 | 分析+设计落盘→代码节点中断→新 runner 同 generation→load_app_state 恢复→跳过已完成→续跑至完成 |
