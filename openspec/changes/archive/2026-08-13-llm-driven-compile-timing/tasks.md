# Tasks: llm-driven-compile-timing

## 1. 移除自动编译与强制机制

- [x] 1.1 删除 `executor_task` 中的定时自动编译块（nodes.py 约 878-902：`round_idx % 4 == 0` 触发、提前退出、partial 跟踪、env 快速失败）
- [x] 1.2 从 `executor_task` 签名删除 `compile_full` 参数（nodes.py:633），删除修复任务强制 full 逻辑（nodes.py:743-744），更新 docstring
- [x] 1.3 env 错误重试的 full 级别改用 LLM 请求的参数（nodes.py:835，`tool_args.get("full")`）
- [x] 1.4 移除 graph.py 修复循环调用处的 `compile_full=(task.get("type") == "fix")` 参数（graph.py:683）

## 2. 提示词重写

- [x] 2.1 重写 `EXECUTOR_SYSTEM_PROMPT` 工作流程：compile_project 改为可选工具说明，任务完成以文件写入为准，输出 `__TASK_DONE__`
- [x] 2.2 在提示词中说明 full 模式差异与调用建议（需要验证类型时用 full=true，不要每轮调用）

## 3. 注释同步

- [x] 3.1 更新 graph.py 修复循环注释与 planner.py `build_fix_task` 中 "full-compile verification" 过时描述

## 4. 测试与验证

- [x] 4.1 补充/更新单元测试：executor 生成期间不触发自动编译，编译仅在 LLM 调用工具或最终门禁时发生
- [x] 4.2 运行 ai-service 测试套件（`ai-design-platform-server/ai-service/tests/`，pytest）确认无回归
- [x] 4.3 手工端到端验证：一次完整生成中，生成期间无自动 compile_status 事件，任务状态正常，最终门禁全量编译与修复循环正常
- [x] 4.4 修复 4.3 验证中发现的问题：增量重规划调用漏传 max_tokens（默认 4096，DeepSeek 思考耗光预算 → 空响应 → 解析失败死路）。新增 `run_incremental_replan`（16384 预算 + 空/解析失败重试一次），替换 graph.py 两处调用点；`tests/test_incremental_replan_retry.py` 覆盖（本机已复现空响应）
- [x] 4.5 第二轮验证发现并修复三个问题：
  - missing-entry 错误带 `kind="env"` 时被 `is_env_error` 的 kind 短路误判为环境错误 → `final_compile_abort` 死路而非 replan 补入口文件。`is_env_error` 重排（missing-entry 检查先于 kind 短路），带 kind 的生产形态测试覆盖（test_env_error_classification.py）
  - skill 模板占位符只替换内容不替换路径 → 生成 `pages/{{entityKey}}/List.vue` 字面量路径。`skill_loader.apply` 对 path 同样替换（test_skill_loader.py）
  - planner 主调用无空响应重试 → 空响应静默降级为 spec-fallback DAG（缺入口文件）。`planner_node` 空响应重试一次（test_planner_empty_retry.py）
