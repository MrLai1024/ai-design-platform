## ADDED Requirements

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

Executor 的 ReAct 循环 SHALL 在调用编译工具时获得前端上报的真实打包错误，并据此生成修复动作，替代原有的文件可读性检查。

#### Scenario: 编译工具返回真实错误

- **WHEN** Executor 调用 `compile_project` 且存在前端上报的错误
- **THEN** 工具返回结构化错误列表（file/line/message），LLM 在下一轮 Reason 中针对错误生成修复代码

#### Scenario: 无上报错误时编译通过

- **WHEN** Executor 调用 `compile_project` 且前端最近一次打包成功
- **THEN** 工具返回成功，任务正常完成

### Requirement: AgentLog 展示真实编译结果

前端 SHALL 将打包结果（成功/失败及错误列表）以编译卡片形式展示在 AI 生成日志中，错误条目可点击定位到对应文件。

#### Scenario: 编译失败卡片

- **WHEN** 打包产生硬错误
- **THEN** AgentLog 出现红色编译卡片，列出错误（file:line — message），点击错误项跳转到对应文件

#### Scenario: 编译成功卡片

- **WHEN** 打包成功
- **THEN** AgentLog 出现绿色编译通过卡片
