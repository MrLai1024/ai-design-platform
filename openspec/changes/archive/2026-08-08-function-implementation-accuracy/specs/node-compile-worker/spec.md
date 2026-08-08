## ADDED Requirements

### Requirement: 服务端真实编译

系统 SHALL 提供后端 Node 编译服务，对持久化项目目录执行真实编译：esbuild bundle 校验（语法、import 解析、SFC 编译）+ vue-tsc `--noEmit` 类型检查，返回结构化错误列表（file/line/column/message/来源）。

#### Scenario: 语法错误检出

- **WHEN** 项目包含语法错误或无法解析的 import
- **THEN** 编译服务返回 esbuild 错误（含文件、行、列、错误文本）

#### Scenario: 类型错误检出

- **WHEN** 项目包含 TypeScript 类型不匹配（如 props 类型与使用方不符）
- **THEN** 编译服务返回 vue-tsc 类型错误（含文件、行、列、错误文本）

#### Scenario: 编译通过

- **WHEN** 项目语法与类型均通过
- **THEN** 编译服务返回成功，错误列表为空

### Requirement: compile_project 调用真实编译

Executor 的 `compile_project` 工具 SHALL 调用 node 编译服务获取真实结果；编译服务不可达或执行失败时 SHALL 返回显式失败（含错误信息），不得在未执行编译时返回"编译通过"。

#### Scenario: 编译服务不可达

- **WHEN** 编译服务 HTTP 调用失败或超时
- **THEN** `compile_project` 返回 ok=False 且错误信息包含服务不可达原因，Executor 可据此重试

#### Scenario: 空项目不编译

- **WHEN** 项目目录不存在或没有可编译文件
- **THEN** 编译服务返回显式错误而非"编译通过"，避免假阳性

### Requirement: 编译响应时效

编译服务 SHALL 在可接受时间内返回结果，支撑 Executor ReAct 循环的实时纠错（esbuild 校验为主路径，vue-tsc 类型检查为完整路径，两者可分层执行）。

#### Scenario: 快速校验先行

- **WHEN** Executor 在生成中途调用 `compile_project`
- **THEN** 编译服务先返回 esbuild 快速校验结果，类型检查结果随后返回或按配置跳过

#### Scenario: 完整检查兜底

- **WHEN** 全部文件生成完成后的最终编译检查
- **THEN** 编译服务执行完整校验（esbuild + vue-tsc），返回最终真实结果
