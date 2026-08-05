## ADDED Requirements

### Requirement: Manager 是唯一与用户对话的 Agent

系统 SHALL 提供唯一全局协调 Agent(Manager),它是整个生成流程中唯一与用户对话的 Agent;各专业 worker 节点不得直接向用户输出对话消息,worker 结果必须回流 Manager 后由 Manager 统一发言。

#### Scenario: 节点完成时 Manager 发言

- **WHEN** 任一 worker 节点执行完成并回流结果
- **THEN** 左侧对话框出现 Manager 的结构化消息,包含该节点产出的摘要

#### Scenario: worker 不直接发言

- **WHEN** 某个 worker 节点执行期间产生中间输出(如代码 token 流)
- **THEN** 这些输出仅进入右侧产物区展示,不出现为对话框中的独立对话消息

### Requirement: 任务分发携带验收标准

Manager SHALL 在分发每个任务时附带验收标准、输入引用、工具边界与约束;worker 按验收标准执行,Manager 按同一标准裁决结果。

#### Scenario: 分发包含验收标准

- **WHEN** Manager 向方案设计 worker 分发任务
- **THEN** dispatch 包含验收标准(如"覆盖 PRD 全部功能点""技术选型符合用户澄清时选择的方案"),worker 上下文包含该验收标准

#### Scenario: 工具边界约束

- **WHEN** Manager 向需求分析 worker 分发任务
- **THEN** dispatch 声明工具边界(如只读需求输入,不写文件),worker 不得越界调用

### Requirement: 分层把关

Manager SHALL 对每个 worker 的回流结果执行三层把关:L1 确定性硬规则(编译/结构/格式/字段完整)、L2 每节点评估(产出与验收标准及上游输入的对应关系)、L3 跨节点一致性(需求→方案→实现整体一致性及跑偏检测)。

#### Scenario: L1 硬规则失败

- **WHEN** 方案设计节点回流的架构 Spec 缺少必需字段(如 directory_tree 为空)
- **THEN** Manager 判定该节点不通过,不进入 L2/L3 评估,直接进入恢复决策

#### Scenario: L3 发现跑偏

- **WHEN** 功能实现节点回流的代码与用户需求要点存在整体性偏离(如需求为数据管理系统,实现为展示页面)
- **THEN** Manager 判定不通过,按恢复流程处理并向用户输出裁决消息

#### Scenario: 把关通过

- **WHEN** 三层把关全部通过
- **THEN** Manager 输出 verdict_card(通过)与 summary_card(节点摘要),并推进到下一节点

### Requirement: 把关时机为节点完成后、用户确认前

Manager 的每节点把关 SHALL 在该节点产物生成完成之后、流程继续之前执行;用户确认"下一步"在把关通过之后。

#### Scenario: 把关先行于确认

- **WHEN** 某节点产物完成且把关未通过
- **THEN** 系统不展示"下一步"确认,先进入恢复流程

### Requirement: 用户输入意图路由

Manager SHALL 对用户在对话框中的输入进行意图识别,区分澄清回答、流程指令、产出反馈三类意图,并按意图路由处理。

#### Scenario: 澄清回答路由

- **WHEN** 用户在头脑风暴阶段回答澄清问题
- **THEN** Manager 将回答更新到对应议程项,并决定是否追问或收敛

#### Scenario: 产出反馈路由

- **WHEN** 用户在某节点产物完成后输入"这个设计不对,XX 功能删掉"
- **THEN** Manager 识别为产出反馈,更新确认项并发起对应节点的回退重做

#### Scenario: 流程指令路由

- **WHEN** 用户输入"开始生成"或"可以了"
- **THEN** Manager 识别为流程指令并推进当前阶段

### Requirement: 节点确认机制

节点产物经 Manager 把关通过后,系统 SHALL 在右侧产物区提供"下一步"操作,同时对话框由 Manager 输出节点完成叙事消息。

#### Scenario: 产物区确认与对话框叙事并存

- **WHEN** 某节点把关通过
- **THEN** 右侧产物区出现"下一步"按钮,对话框同时出现 Manager 的 summary_card 消息
