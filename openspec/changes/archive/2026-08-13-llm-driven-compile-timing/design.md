# Design: llm-driven-compile-timing

## Context

代码生成阶段（功能开发节点）的编译目前有三层硬编码时机：

1. `executor_task` 每 4 轮自动编译一次（`round_idx % 4 == 0`，nodes.py:880），结果只发事件、不进模型上下文
2. `EXECUTOR_SYSTEM_PROMPT` 强制"全部文件生成后调用 compile_project 检查 → 修复 → 编译通过后输出 __TASK_DONE__"（nodes.py:386-391）
3. 修复任务强制 `full=True`（nodes.py:743），使其内部编译都含 vue-tsc 类型检查

`compile_project` 本身已注册为工具（registry.py:137），LLM 调用时结果会回流消息上下文。最终门禁（graph.py Step 4）已实现"所有任务完成后全量编译 + replan/fix/abort 修复循环"。

目标：生成期间编译完全由 LLM 自主决定；系统保证只剩最终门禁一处；无硬编码时机。

## Goals / Non-Goals

**Goals**

- 生成期间零强制编译：无自动触发、无提示词强制、无模式强制
- 编译保持为 LLM 可调用工具，真实结果回流消息上下文
- 保留最终门禁作为系统级正确性保证
- 移除 `compile_full` 机制（参数、强制、透传）
- 编译策略变更点集中在提示词与工具注册表，可扩展、可逆

**Non-Goals**

- 不引入策略对象/配置框架（如 CompileStrategy）——编译时机唯一决策者是 LLM，单一模式不需要抽象层
- 不改 node-compiler worker 协议与编译工具实现
- 不做"只读查看结果"与"触发编译"的工具区分（`get_compile_errors` 维持现状）
- 不改最终门禁的修复策略与轮数上限
- 不改前端协议与展示

## Decisions

### D1: 编译时机交给 LLM，不引入策略抽象

**决策**：删除定时自动编译与提示词强制，编译完全由 LLM 通过 `compile_project` 工具自主调用。

**备选**：CompileStrategy 策略对象（`during_generation: never/auto_every_n_rounds/on_request`）。不选——本次目标即单一模式（LLM 自主），策略对象是投机性泛化。扩展性通过既有扩展点获得：改时机 = 改提示词/工具注册；加验证门禁（如 lint）= 注册新工具。决策点集中、可逆，无运行时抽象成本。

### D2: 删除自动编译块，能力保留在 LLM 调用路径

**决策**：删除 nodes.py 中 `round_idx % 4 == 0` 自动编译块（含其 partial 跟踪、env 快速失败、提前退出）。

partial 跟踪与 env 错误处理在 LLM 调用 `compile_project` 的工具分支（nodes.py:808-849）中原样保留——能力不丢失，只是触发方式改变。planning-gap 检测（graph.py Step 3.5）失去生成期间的输入，由最终门禁的 `missing_file → replan` 兜住。

### D3: EXECUTOR_SYSTEM_PROMPT 重写为工具说明式

**决策**：工作流从"编译→修复→DONE"改为"写文件 → 可选编译验证 → `__TASK_DONE__`"；`compile_project` 以工具形式说明（用途、full 模式差异、避免每轮调用）。

提示词是 LLM 行为的引导面——工具仍注册，调不调由模型自行判断。

### D4: 移除 compile_full 机制

**决策**：`executor_task` 签名删除 `compile_full` 参数；删除修复任务的 full 强制与自动编译处的 full 透传；env 错误重试保留，full 级别改用 LLM 请求的参数（`tool_args.get("full")`）。graph.py:683 调用处同步移除参数。

### D5: 任务状态语义：done = 文件写入

**决策**：未调用编译的任务 `compile_errors=None` → 状态 done（现有逻辑天然支持，零代码改动）。LLM 调用编译且报错 → failed → 既有 retry/replan 机制处理。

### D6: 最终门禁不变

**决策**：graph.py Step 4 全量编译门禁与 `plan_final_compile_fix`（replan/fix/abort）保持现状，轮数上限等常量不变。

## Risks / Trade-offs

- [planning-gap 信号延迟] 生成期间不再有 partial 编译，缺失 import 到最终门禁才暴露 → 门禁 `missing_file → replan` 兜住；修复轮数有上限，不会死循环
- [修复任务"盲修"] 不再强制 full，类型错误可见性下降、收敛变慢 → 工具描述说明 full 模式；门禁每轮全量编译验证收敛
- [LLM 行为不确定] 模型可能过度调用编译或完全不调 → 提示词引导调用频率；系统保证（最终门禁）不依赖模型行为
- [LLM 空响应] DeepSeek 思考模式可耗尽 max_tokens 预算返回空 content，历史路径曾因此死路（增量重规划解析失败、planner 静默降级 fallback DAG）→ 增量重规划与 planner 主调用均已加空响应重试 + 16384 预算（见 tasks 4.4/4.5）
- [任务状态语义变化] task done 不再代表编译通过 → 前端 task_complete 事件无编译字段变化；最终 compile_status 仍是权威展示

## Migration Plan

- 单次代码改动，无数据迁移；回滚 = 恢复自动编译块与参数（git 历史可查）
- 前端无部署依赖；生成期间 AgentLog 编译卡片变少属预期变化

## Open Questions

- 无。`get_compile_errors` 若未来需要改为纯只读查询（不触发编译），是独立改动，不在本次范围。
