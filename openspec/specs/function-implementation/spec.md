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

### Requirement: 编译通过判据

功能实现节点 SHALL 以 node 编译服务的真实结果作为编译通过的判据；前端 esbuild 上报错误作为辅助信号参与展示与修复，不得反向覆盖为"通过"。

#### Scenario: worker 失败即任务失败

- **WHEN** 最终编译检查中 node 编译服务返回错误
- **THEN** 任务判定为失败，错误进入 Executor 修复循环

#### Scenario: 前端反馈补充展示

- **WHEN** node 编译通过但前端预览 esbuild 报告可恢复错误
- **THEN** 编译结果仍为通过，前端错误仅作为预览降级提示展示
