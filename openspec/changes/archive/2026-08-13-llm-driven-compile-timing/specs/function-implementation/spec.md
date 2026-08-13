## ADDED Requirements

### Requirement: 编译时机由 Executor 自主决定

功能实现节点 SHALL 将编译作为 Executor 的可选工具，不在生成期间设置任何自动或定时编译触发（轮次计数、周期轮询等）；Executor 在需要验证 import 路径、接口契约或类型时自行调用编译工具查看结果，工具返回的真实结果 SHALL 进入模型消息上下文供下一轮决策。任务完成状态 SHALL 以任务范围文件全部写入为准，不要求编译通过；系统 SHALL 在所有任务完成后统一执行一次全量编译（esbuild + vue-tsc）作为最终门禁，失败由门禁修复循环按错误分类处理。

#### Scenario: 生成期间无自动编译

- **WHEN** Executor 生成文件期间未主动调用编译工具
- **THEN** 后端不触发任何编译；编译入口仅剩 Executor 主动调用 `compile_project` 工具与系统最终门禁

#### Scenario: 编译结果回流供模型决策

- **WHEN** Executor 调用 `compile_project` 且 node 编译服务返回结果（成功或错误列表）
- **THEN** 真实结果进入下一轮模型消息上下文，由模型自行决定修复或继续，后端不预设修复路径

#### Scenario: 任务完成以文件写入为准

- **WHEN** Executor 写完任务全部文件且未调用编译工具
- **THEN** 任务判定完成，不产生编译失败状态

#### Scenario: 修复任务不强制编译模式

- **WHEN** 最终门禁产生修复任务且 Executor 调用编译工具
- **THEN** 编译模式（full/quick）由模型通过工具参数自行选择，后端不强制

#### Scenario: 最终门禁统一编译

- **WHEN** 所有任务完成后
- **THEN** 系统执行一次全量编译（esbuild + vue-tsc），失败按错误分类进入增量重规划、修复任务或中止
