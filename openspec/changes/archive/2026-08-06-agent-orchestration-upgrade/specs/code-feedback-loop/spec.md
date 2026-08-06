## MODIFIED Requirements

### Requirement: 反馈端点接收

后端 SHALL 提供 `POST /api/v1/generation/feedback` 端点,接收 `{ generation_id, feedback }` 并将其注入对应 generation 的 Manager 恢复决策流程,作为问题记录与重派反馈的输入。

#### Scenario: 反馈成功接收

- **WHEN** 前端 POST 反馈到端点，携带有效的 generation_id 和反馈文本
- **THEN** 后端返回 200，反馈文本被写入该 generation 的问题记录，进入 Manager 恢复决策

#### Scenario: 无效 generation_id

- **WHEN** 前端 POST 反馈到端点，携带不存在的 generation_id
- **THEN** 后端返回 404 错误

### Requirement: Manager 处置用户反馈

收到用户反馈后,Manager SHALL 对反馈分类(遗漏/纠偏/范围变更),并据此决策:遗漏与纠偏重派对应 worker 并携带反馈;范围变更以 confirm_card 请求用户确认后更新需求。

#### Scenario: 遗漏类反馈

- **WHEN** 用户反馈指出某组件缺失，且架构 Spec 中确实定义了该组件
- **THEN** Manager 重派功能实现 worker，反馈作为重派任务的一部分进入任务 DAG

#### Scenario: 范围变更类反馈

- **WHEN** 用户反馈提出新增超出当前需求范围的功能
- **THEN** Manager 输出 confirm_card 请求用户确认，确认后更新需求规格并继续

## ADDED Requirements

### Requirement: 反馈处置结果卡片

每条用户反馈的处置结果 SHALL 在对话框中由 Manager 呈现为一条折叠摘要卡片(反馈摘要 + 处置动作 + 结果)。

#### Scenario: 卡片默认折叠

- **WHEN** 反馈对应的处置与重派执行完成
- **THEN** 对话框出现一行折叠摘要卡片，展开可见处置过程（分类、重派任务、验证结果）
