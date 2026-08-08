# compile-feedback Specification

## Purpose

定义编译反馈闭环：node 编译服务（esbuild + vue-tsc）的真实结果作为编译通过的唯一判据，前端 esbuild 打包错误作为辅助信号结构化上报后端并暂存于 generation 运行时状态，Executor 在 ReAct 循环中消费真实编译错误以生成修复动作，最终由 AgentLog 以编译卡片形式向用户展示编译结果。

## Requirements

### Requirement: 打包错误结构化上报

前端 SHALL 将 esbuild 打包失败产生的错误（含文件路径、行号、列号、错误文本）结构化后通过 HTTP 端点上报至后端，并携带 generation_id 与阶段标识。

#### Scenario: 硬错误上报

- **WHEN** 生成完成信号后打包仍失败（非 partial 错误）
- **THEN** 前端将错误列表 POST 至后端 compile feedback 端点，包含 `generation_id`、错误数组（file/line/column/text）

#### Scenario: partial 错误不上报

- **WHEN** 流式生成过程中出现 `Could not resolve` 类可恢复错误
- **THEN** 前端不发送上报请求

### Requirement: 后端接收并暂存编译错误

后端 SHALL 提供 compile feedback 接收通道，将上报的错误写入对应 generation 的运行时状态，供 Executor 后续消费。

#### Scenario: 错误写入 generation 状态

- **WHEN** 后端收到某 generation_id 的编译错误上报
- **THEN** 错误列表被存入该 generation 对应的状态对象，可被同一会话的后续节点读取

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

### Requirement: AgentLog 展示真实编译结果

前端 SHALL 将打包结果（成功/失败及错误列表）以编译卡片形式展示在 AI 生成日志中，错误条目可点击定位到对应文件。

#### Scenario: 编译失败卡片

- **WHEN** 打包产生硬错误
- **THEN** AgentLog 出现红色编译卡片，列出错误（file:line — message），点击错误项跳转到对应文件

#### Scenario: 编译成功卡片

- **WHEN** 打包成功
- **THEN** AgentLog 出现绿色编译通过卡片
