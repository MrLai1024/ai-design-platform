# compile-feedback Specification

## Purpose

定义前端打包与运行错误的反馈闭环：前端将 esbuild 打包错误与运行时错误结构化上报后端并暂存于 generation 运行时状态，Verifier 的四层验证以 L1 编译为第一道验证并消费真实编译错误，Debugger 以错误列表为根因诊断证据，最终由 AgentLog 以编译卡片形式向用户展示真实编译结果。

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

后端 SHALL 提供 compile feedback 接收通道，将上报的错误写入对应 generation 的运行时状态，供 Verifier 与 Debugger 消费。

#### Scenario: 错误写入 generation 状态

- **WHEN** 后端收到某 generation_id 的编译错误上报
- **THEN** 错误列表被存入该 generation 对应的状态对象，可被 Verifier 的 L1 验证与 Debugger 的证据链读取

### Requirement: Verifier 消费真实编译错误

Verifier 的四层验证信号 SHALL 以 L1(编译)为第一道验证：Verifier 在验证时获得前端上报的真实打包错误,并据此判定验证失败；Debugger 以该错误列表作为根因诊断证据。

#### Scenario: 编译工具返回真实错误

- **WHEN** Verifier 执行 L1 验证且存在前端上报的错误
- **THEN** 验证判定失败,错误列表(file/line/message)作为证据交给 Debugger 诊断

#### Scenario: 无上报错误时编译通过

- **WHEN** Verifier 执行 L1 验证且前端最近一次打包成功
- **THEN** L1 验证通过,继续 L2 契约验证

### Requirement: AgentLog 展示真实编译结果

前端 SHALL 将打包结果（成功/失败及错误列表）以编译卡片形式展示在 AI 生成日志中，错误条目可点击定位到对应文件。

#### Scenario: 编译失败卡片

- **WHEN** 打包产生硬错误
- **THEN** AgentLog 出现红色编译卡片，列出错误（file:line — message），点击错误项跳转到对应文件

#### Scenario: 编译成功卡片

- **WHEN** 打包成功
- **THEN** AgentLog 出现绿色编译通过卡片

### Requirement: 运行时错误上报

前端 SHALL 将 E2E 执行与页面运行期间的 console 错误、未捕获异常及网络请求失败结构化上报至后端，作为 Verifier L3 验证与 Test Diagnoser 诊断的证据。

#### Scenario: console 错误上报

- **WHEN** E2E 执行期间页面产生未捕获异常
- **THEN** 前端将该异常(消息、堆栈、发生用例)上报后端并关联 generation_id
