# code-feedback-loop Specification

## Purpose

后端反馈接收 → Planner 自我审查（对比设计文档 → 补充 Task DAG）→ Executor 续写 → 反馈卡片折叠。实现用户反馈驱动的 Agent 自我纠偏闭环，使生成产出与设计文档保持一致。

## Requirements

### Requirement: 反馈端点接收

后端 SHALL 提供 `POST /api/v1/generation/feedback` 端点，接收 `{ generation_id, feedback }` 并将其注入对应 generation 的 Planner ReAct 循环。

#### Scenario: 反馈成功接收

- **WHEN** 前端 POST 反馈到端点，携带有效的 generation_id 和反馈文本
- **THEN** 后端返回 200，反馈文本被保存到该 generation 的状态中

#### Scenario: 无效 generation_id

- **WHEN** 前端 POST 反馈到端点，携带不存在的 generation_id
- **THEN** 后端返回 404 错误

### Requirement: Planner 自我审查

收到用户反馈后，Planner SHALL 对比设计文档与已生成文件，找出遗漏或差异，输出补充 Task DAG。

#### Scenario: 发现遗漏

- **WHEN** 用户反馈指出某组件缺失，且设计文档中确实定义了该组件
- **THEN** Planner 输出包含该组件对应 task 的补充 DAG

#### Scenario: 无遗漏

- **WHEN** 用户反馈描述的问题在已生成文件中已被覆盖
- **THEN** Planner 输出空 DAG，AgentLog 追加 "经审查未发现遗漏" 卡片

### Requirement: Executor 执行补充任务

Planner 输出补充 DAG 后，Executor SHALL 按顺序执行新增 task，与初次生成流程一致。

#### Scenario: 补充文件生成

- **WHEN** Planner 输出补充 DAG 包含 task-8（生成 UserProfile.vue）
- **THEN** Executor 依次执行 task，AgentLog 实时展示 task 分组、工具调用、文件生成与编译结果

### Requirement: 反馈卡片折叠

每条完成的反馈 SHALL 在 AgentLog 中显示为一条折叠摘要卡片。

#### Scenario: 卡片默认折叠

- **WHEN** 反馈对应的所有补充 task 执行完成
- **THEN** AgentLog 中该反馈显示为一行折叠摘要（反馈文本摘要 + 处理结果），历史 task 执行过程默认隐藏

#### Scenario: 点击展开历史

- **WHEN** 用户点击折叠的反馈卡片
- **THEN** 卡片展开，显示该反馈触发的完整 task 执行过程（包含思考气泡、工具调用、文件生成等子卡片）
