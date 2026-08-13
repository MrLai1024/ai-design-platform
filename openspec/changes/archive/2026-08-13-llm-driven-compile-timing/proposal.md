# Proposal: llm-driven-compile-timing

## Why

功能开发节点（代码生成）的编译时机目前是硬编码的：Executor 每 4 轮自动编译一次（`round_idx % 4 == 0`），`EXECUTOR_SYSTEM_PROMPT` 强制"编译通过才算任务完成"，修复任务还被强制 full 编译模式。这产生大量与代码正确性无关的编译开销，时机与任务、文件状态脱钩。目标是让编译成为 LLM 自主决策的工具——模型在需要验证时调用查看结果，所有代码生成完后由系统统一执行一次全量编译，机制可扩展、无硬编码时机。

## What Changes

- **移除** Executor 循环中的定时自动编译（`round_idx % 4 == 0` 块，含提前退出、partial 跟踪与 env 快速失败）——生成期间编译入口只剩 LLM 主动调用与系统最终门禁
- **重写** `EXECUTOR_SYSTEM_PROMPT` 工作流程：`compile_project` 从强制步骤改为可选工具说明；任务完成以任务范围文件全部写入为准，输出 `__TASK_DONE__` 不再要求编译通过
- **移除** `compile_full` 机制：`executor_task` 参数、修复任务的 full 强制、env 重试的 full 透传；编译模式（full/quick）由 LLM 调用工具时自行选择
- **保留** 最终门禁：所有任务完成后系统执行一次全量编译（esbuild + vue-tsc），失败按错误分类进入 replan/fix/abort 修复循环
- **状态语义变化**：未调用编译的任务以文件写入判定 done，不产生编译失败状态；编译错误只来自 LLM 主动调用或最终门禁
- **同步更新** 过时注释（graph.py 修复循环、planner.py `build_fix_task` 中 "full-compile verification" 描述）

## Capabilities

### New Capabilities
<!-- 无新能力 -->

### Modified Capabilities

- `function-implementation`：新增"编译时机由 Executor 自主决定"需求——生成期间无自动/定时编译触发，编译是 LLM 可选工具，最终门禁统一编译

## Impact

- `ai-design-platform-server/ai-service/app/services/generation/nodes.py` — `executor_task`（删除自动编译块与 `compile_full` 参数/强制）、`EXECUTOR_SYSTEM_PROMPT` 重写
- `ai-design-platform-server/ai-service/app/services/generation/graph.py` — 修复循环调用处移除 `compile_full` 参数
- `ai-design-platform-server/ai-service/app/services/generation/planner.py` — 注释同步（无逻辑变更）
- 前端无协议变更：生成期间 `compile_status` 事件减少（仅 LLM 主动调用与最终门禁时出现），AgentLog 展示不受影响
