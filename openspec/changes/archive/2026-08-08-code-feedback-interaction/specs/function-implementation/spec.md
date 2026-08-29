## ADDED Requirements

### Requirement: 反馈现场恢复

功能实现节点 SHALL 在收到用户反馈并触发 fresh-start 时恢复工程现场:已生成文件清单从 `code_result`(generated_files 的序列化)反序列化恢复,缺失时从持久化项目目录扫描磁盘兜底;上次最终编译错误与失败任务摘要(失败任务的 id/描述/failure_kind/缺失文件)SHALL 注入新 state 供规划使用。恢复过程不得匹配、解析或分类反馈文本本身,任何输入走同一路径;历史不可得时(如服务重启后旧状态丢失)不得伪造历史,仅依赖磁盘上可恢复的事实。

#### Scenario: 反馈后恢复已生成文件

- **WHEN** 用户提交反馈触发 fresh-start 且 `code_result` 非空
- **THEN** `generated_files` 从 `code_result` 反序列化恢复,planner 的反馈 prompt 包含已生成文件清单

#### Scenario: code_result 缺失时磁盘兜底

- **WHEN** `code_result` 为空或损坏
- **THEN** 从持久化项目目录扫描文件恢复清单(跳过点目录、文件数有上限),不伪造任何文件内容

#### Scenario: 恢复编译状态与失败任务

- **WHEN** 旧 runner 状态存在且 feedback fresh-start 触发
- **THEN** 上次 compile_errors 与失败任务摘要注入新 state;旧 runner 不存在时仅依赖磁盘兜底,不产生虚构的失败记录

### Requirement: Planner 基于现场反馈规划

Planner 的反馈规划 SHALL 以现场事实为输入:已生成文件清单(带大小)、上次编译状态、失败任务列表,与反馈文本一同作为 prompt 上下文;反馈文本不做关键字匹配、不做语义分类,agent 基于现场自主判断补任务/修复/无需修改。反馈场景下 agent 明确输出空任务列表 SHALL 作为合法结果正常收尾(不报 "Planner produced no tasks" 死路);增量规划输出解析失败不得静默收尾,照常报错。

#### Scenario: 反馈 prompt 注入现场清单

- **WHEN** 反馈存在且现场已恢复
- **THEN** prompt 包含已生成文件清单(带大小)、上次编译错误、失败任务列表,反馈文本原样附于其后

#### Scenario: 反馈后空 delta 正常收尾

- **WHEN** 反馈存在且 planner 明确输出空任务列表(JSON 解析成功)
- **THEN** 视为"无需修改",正常进入收尾流程,不报 "Planner produced no tasks"

#### Scenario: 解析失败不得静默收尾

- **WHEN** 增量规划输出 JSON 解析失败且兜底为空任务列表
- **THEN** 照常报错,不得以"空 delta 容错"掩盖

### Requirement: Agent 对话消息可见

功能实现节点 SHALL 将 Executor 每轮正式回复(content)以 `agent_message` 事件流式发给前端,AgentLog 以对话气泡展示模型原文。agent 对话文本 SHALL 100% 来自模型输出:后端不得拼接、替换或改写任何展示文本,不得插入"收到反馈"等模板回执;`__TASK_DONE__` 等内部标记不得展示,空白内容不发事件。

#### Scenario: executor 回复流式展示

- **WHEN** Executor 某轮输出非空 content
- **THEN** 以 `agent_message` 事件发出,前端渲染为对话气泡,展示模型原文

#### Scenario: 内部标记与空白内容过滤

- **WHEN** content 仅含 `__TASK_DONE__` 等内部标记或为空白
- **THEN** 不发出 agent_message 事件;正常回复中夹带的标记在展示时去除

#### Scenario: 后端零模板回执

- **WHEN** 用户提交反馈进入新一轮生成
- **THEN** 前端展示的 agent 文本全部来自模型输出(content/reasoning),后端不产生任何固定字符串回执

### Requirement: 后端事件零口吻

后端事件 SHALL 只携带结构化数据(decision / missing_files / failed_task_ids / errors 等),不含后端拼接的人类文案;planner_reflect、最终编译修复等系统事件删除 `message` 拼接字段,展示文案按归属渲染:agent 对话气泡展示模型原文,系统状态卡由前端按 decision 渲染短描述。planner_dag 事件的 reasoning 为模型输出,原样透传。

#### Scenario: 系统事件只带数据

- **WHEN** planner_reflect 或最终编译修复事件发出
- **THEN** 事件仅含 decision 与结构化数据字段,无后端拼接的中文 message

#### Scenario: 前端按 decision 渲染状态卡

- **WHEN** 前端收到 planner_reflect 事件
- **THEN** 状态卡文案由前端按 decision 渲染(未知 decision 显示 key 本身),不展示后端拼接文本
