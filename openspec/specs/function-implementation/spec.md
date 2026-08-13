# function-implementation Specification

## Purpose

定义功能实现节点（Executor 多智能体）的生成行为：以架构 Spec 与设计文档为上下文输入，通过项目读取工具查看项目现状，将生成文件持久化到统一事实源，并以 node 编译服务真实结果作为编译通过的唯一判据。

## Requirements

### Requirement: Executor 可见设计文档

功能实现节点的每个 Executor 任务 SHALL 在上下文中携带设计文档引用：任务对应 Spec 片段（组件/页面/数据模型契约）+ 人读设计文档摘要，使生成代码与设计文档保持一致。

#### Scenario: 任务携带 Spec 片段

- **WHEN** Executor 开始执行某个 task
- **THEN** 用户消息包含该 task 对应的 Spec 片段（component_tree 项、pages 项、相关 data_model/api_contracts）与设计文档摘要

#### Scenario: 设计要素体现在代码中

- **WHEN** Spec 声明某页面含指定交互与数据
- **THEN** Executor 生成的页面代码包含对应交互元素与数据绑定，而非空壳

### Requirement: 项目读取工具

功能实现节点 SHALL 提供 `read_file` / `list_files` / `search_project` 工具，Executor 可在写作前查看项目现状（文件列表、文件内容、关键词检索），确保增量写入与已生成文件一致。

#### Scenario: 查看项目现状

- **WHEN** Executor 调用 `list_files`
- **THEN** 返回持久化项目目录中的文件清单（路径 + 大小/行数）

#### Scenario: 读取已有文件

- **WHEN** Executor 调用 `read_file` 且目标文件存在
- **THEN** 返回文件完整内容；文件不存在时返回显式错误

#### Scenario: 检索相关代码

- **WHEN** Executor 调用 `search_project` 检索某接口或组件名
- **THEN** 返回命中文件及上下文片段

### Requirement: 持久化项目单一事实源

功能实现节点 SHALL 将所有生成文件写入持久化项目目录（`data/generated/<app_id>/`），该目录是后端、前端预览与编译服务共享的唯一事实源；`use_skill` 生成的文件 SHALL 同样进入前端文件事件流，确保预览与后端状态一致。

#### Scenario: 全部文件落盘

- **WHEN** Executor 或 skill 生成文件
- **THEN** 文件写入持久化项目目录，前端通过文件事件获得全部文件（含 skill 文件）

#### Scenario: 重启后可恢复

- **WHEN** 服务重启后加载同一 app_id
- **THEN** 项目目录内文件完整可读，可直接作为后续编译与增量开发输入

### Requirement: 编译时机由 Executor 自主决定

功能实现节点 SHALL 将编译作为 Executor 的可选工具，不在生成期间设置任何自动或定时编译触发（轮次计数、周期轮询等）；Executor 在需要验证 import 路径、接口契约或类型时自行调用编译工具查看结果，工具返回的真实结果 SHALL 进入模型消息上下文供下一轮决策。任务完成状态 SHALL 以任务范围文件全部写入为准，不要求编译通过；系统 SHALL 在所有任务完成后统一执行一次全量编译（esbuild + vue-tsc）作为最终门禁，失败由门禁修复循环按错误分类处理。

#### Scenario: 生成期间无自动编译

- **WHEN** Executor 生成文件期间未主动调用编译工具
- **THEN** 后端不触发任何编译；编译入口仅剩 Executor 主动调用 `compile_project` 工具与系统最终门禁

#### Scenario: 编译结果回流供模型决策

- **WHEN** Executor 调用 `compile_project` 且 node 编译服务返回结果（成功或错误列表）
- **THEN** 真实结果进入下一轮模型消息上下文，由模型自行决定修复或继续，后端不预设修复路径

#### Scenario: 任务完成以文件写入为准

- **WHEN** Executor 写完任务全部文件且未调用编译工具
- **THEN** 任务判定完成，不产生编译失败状态

#### Scenario: 修复任务不强制编译模式

- **WHEN** 最终门禁产生修复任务且 Executor 调用编译工具
- **THEN** 编译模式（full/quick）由模型通过工具参数自行选择，后端不强制

#### Scenario: 最终门禁统一编译

- **WHEN** 所有任务完成后
- **THEN** 系统执行一次全量编译（esbuild + vue-tsc），失败按错误分类进入增量重规划、修复任务或中止

### Requirement: 编译通过判据

功能实现节点 SHALL 以 node 编译服务的真实结果作为编译通过的判据；前端 esbuild 上报错误作为辅助信号参与展示与修复，不得反向覆盖为"通过"。

#### Scenario: worker 失败即任务失败

- **WHEN** 最终编译检查中 node 编译服务返回错误
- **THEN** 任务判定为失败，错误进入 Executor 修复循环

#### Scenario: 前端反馈补充展示

- **WHEN** node 编译通过但前端预览 esbuild 报告可恢复错误
- **THEN** 编译结果仍为通过，前端错误仅作为预览降级提示展示

### Requirement: 反馈现场恢复

功能实现节点 SHALL 在收到用户反馈并触发 fresh-start 时恢复工程现场：已生成文件清单从 `code_result`（generated_files 的序列化）反序列化恢复，缺失时从持久化项目目录扫描磁盘兜底；上次最终编译错误与失败任务摘要（失败任务的 id/描述/failure_kind/缺失文件）SHALL 注入新 state 供规划使用。恢复过程不得匹配、解析或分类反馈文本本身，任何输入走同一路径；历史不可得时（如服务重启后旧状态丢失）不得伪造历史，仅依赖磁盘上可恢复的事实。

#### Scenario: 反馈后恢复已生成文件

- **WHEN** 用户提交反馈触发 fresh-start 且 `code_result` 非空
- **THEN** `generated_files` 从 `code_result` 反序列化恢复，planner 的反馈 prompt 包含已生成文件清单

#### Scenario: code_result 缺失时磁盘兜底

- **WHEN** `code_result` 为空或损坏
- **THEN** 从持久化项目目录扫描文件恢复清单（跳过点目录、文件数有上限），不伪造任何文件内容

#### Scenario: 恢复编译状态与失败任务

- **WHEN** 旧 runner 状态存在且 feedback fresh-start 触发
- **THEN** 上次 compile_errors 与失败任务摘要注入新 state；旧 runner 不存在时仅依赖磁盘兜底，不产生虚构的失败记录

### Requirement: Planner 基于现场反馈规划

Planner 的反馈规划 SHALL 以现场事实为输入：已生成文件清单（带大小）、上次编译状态、失败任务列表，与反馈文本一同作为 prompt 上下文；反馈文本不做关键字匹配、不做语义分类，agent 基于现场自主判断补任务/修复/无需修改。反馈场景下 agent 明确输出空任务列表 SHALL 作为合法结果正常收尾（不报 "Planner produced no tasks" 死路）；增量规划输出解析失败不得静默收尾，照常报错。

#### Scenario: 反馈 prompt 注入现场清单

- **WHEN** 反馈存在且现场已恢复
- **THEN** prompt 包含已生成文件清单（带大小）、上次编译错误、失败任务列表，反馈文本原样附于其后

#### Scenario: 反馈后空 delta 正常收尾

- **WHEN** 反馈存在且 planner 明确输出空任务列表（JSON 解析成功）
- **THEN** 视为"无需修改"，正常进入收尾流程，不报 "Planner produced no tasks"

#### Scenario: 解析失败不得静默收尾

- **WHEN** 增量规划输出 JSON 解析失败且兜底为空任务列表
- **THEN** 照常报错，不得以"空 delta 容错"掩盖

### Requirement: Agent 对话消息可见

功能实现节点 SHALL 将 Executor 每轮正式回复（content）以 `agent_message` 事件流式发给前端，AgentLog 以对话气泡展示模型原文。agent 对话文本 SHALL 100% 来自模型输出：后端不得拼接、替换或改写任何展示文本，不得插入"收到反馈"等模板回执；`__TASK_DONE__` 等内部标记不得展示，空白内容不发事件。

#### Scenario: executor 回复流式展示

- **WHEN** Executor 某轮输出非空 content
- **THEN** 以 `agent_message` 事件发出，前端渲染为对话气泡，展示模型原文

#### Scenario: 内部标记与空白内容过滤

- **WHEN** content 仅含 `__TASK_DONE__` 等内部标记或为空白
- **THEN** 不发出 agent_message 事件；正常回复中夹带的标记在展示时去除

#### Scenario: 后端零模板回执

- **WHEN** 用户提交反馈进入新一轮生成
- **THEN** 前端展示的 agent 文本全部来自模型输出（content/reasoning），后端不产生任何固定字符串回执

### Requirement: 后端事件零口吻

后端事件 SHALL 只携带结构化数据（decision / missing_files / failed_task_ids / errors 等），不含后端拼接的人类文案；planner_reflect、最终编译修复等系统事件删除 `message` 拼接字段，展示文案按归属渲染：agent 对话气泡展示模型原文，系统状态卡由前端按 decision 渲染短描述。planner_dag 事件的 reasoning 为模型输出，原样透传。

#### Scenario: 系统事件只带数据

- **WHEN** planner_reflect 或最终编译修复事件发出
- **THEN** 事件仅含 decision 与结构化数据字段，无后端拼接的中文 message

#### Scenario: 前端按 decision 渲染状态卡

- **WHEN** 前端收到 planner_reflect 事件
- **THEN** 状态卡文案由前端按 decision 渲染（未知 decision 显示 key 本身），不展示后端拼接文本
