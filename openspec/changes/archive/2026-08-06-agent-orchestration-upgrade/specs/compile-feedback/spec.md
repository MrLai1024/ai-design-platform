## MODIFIED Requirements

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

## ADDED Requirements

### Requirement: 运行时错误上报

前端 SHALL 将 E2E 执行与页面运行期间的 console 错误、未捕获异常及网络请求失败结构化上报至后端，作为 Verifier L3 验证与 Test Diagnoser 诊断的证据。

#### Scenario: console 错误上报

- **WHEN** E2E 执行期间页面产生未捕获异常
- **THEN** 前端将该异常(消息、堆栈、发生用例)上报后端并关联 generation_id
