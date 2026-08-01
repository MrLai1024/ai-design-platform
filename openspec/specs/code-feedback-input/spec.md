# code-feedback-input Specification

## Purpose

AgentLog 底部反馈输入框 + 停止按钮 UI，Enter 发送 / Shift+Enter 换行，流式状态联动。为用户提供在功能开发节点中发现遗漏时描述问题、纠正 Agent 生成结果的输入入口。

## Requirements

### Requirement: 反馈输入框始终可见

AgentLog 底部 SHALL 始终展示一个文本输入框，无论是否正在流式生成。

#### Scenario: 输入框始终渲染

- **WHEN** AgentLog 组件被挂载
- **THEN** 底部显示一个固定文本输入框，不随日志内容滚动

### Requirement: Enter 发送、Shift+Enter 换行

输入框 SHALL 在用户按下 Enter（无 Shift）时提交反馈，Shift+Enter 时插入换行符。

#### Scenario: Enter 提交

- **WHEN** 用户在输入框中输入文本后按下 Enter（无 Shift 修饰键）
- **THEN** 系统提交反馈文本，输入框清空

#### Scenario: Shift+Enter 换行

- **WHEN** 用户在输入框中按下 Shift+Enter
- **THEN** 在光标位置插入一个换行符，不提交

### Requirement: 发送状态联动

输入框 SHALL 根据当前流式状态调整交互可用性。

#### Scenario: 生成中禁止发送

- **WHEN** 功能开发节点正在流式生成（isStreaming 为 true）
- **THEN** Enter 键提交行为被禁用，输入框显示灰色提示"生成中..."

#### Scenario: 空闲时可发送

- **WHEN** 流式生成结束（isStreaming 为 false）且输入框有内容
- **THEN** Enter 键正常提交

### Requirement: 停止执行按钮

AgentLog 底部输入框右侧 SHALL 显示一个停止按钮。

#### Scenario: 生成中停止按钮可用

- **WHEN** 正在流式生成
- **THEN** 停止按钮以红色显示，点击后取消当前 SSE 连接，AgentLog 追加一条 ⏹ 终止标记卡片

#### Scenario: 空闲时停止按钮不可用

- **WHEN** 未在流式生成
- **THEN** 停止按钮以灰色显示，点击无效果

### Requirement: 停止后输入框立即可用

停止操作完成后 SHALL 使反馈输入框立即恢复可用。

#### Scenario: 停止后可立即输入

- **WHEN** 用户点击停止按钮且流被成功终止
- **THEN** 反馈输入框恢复可编辑状态，Enter 键可正常提交
