## MODIFIED Requirements

### Requirement: Executor 消费真实编译错误

Executor 的 ReAct 循环 SHALL 在调用编译工具时获得真实编译错误——以 node 编译服务（esbuild + vue-tsc）的结果为唯一通过判据，前端上报的打包错误作为辅助信号参与展示，并据此生成修复动作。不再以"前端未上报"推断编译通过。

#### Scenario: 编译工具返回 worker 真实错误

- **WHEN** Executor 调用 `compile_project` 且 node 编译服务返回错误
- **THEN** 工具返回结构化错误列表（file/line/column/message/来源），LLM 在下一轮 Reason 中针对错误生成修复代码

#### Scenario: worker 不可达时显式失败

- **WHEN** Executor 调用 `compile_project` 且编译服务不可达
- **THEN** 工具返回失败并携带不可达原因，不得返回"编译通过"

#### Scenario: 编译通过

- **WHEN** Executor 调用 `compile_project` 且 node 编译服务校验通过（无 esbuild 与 vue-tsc 错误）
- **THEN** 工具返回成功，任务正常完成

#### Scenario: 前端反馈作为辅助信号

- **WHEN** node 编译通过但前端 esbuild 上报错误
- **THEN** 编译结果保持通过，前端错误仅作为预览降级提示在 AgentLog 展示
