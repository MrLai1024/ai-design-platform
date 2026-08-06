# function-implementation Specification

## Purpose

功能实现节点内部多角色系统：Planner（基于架构 Spec 生成任务 DAG）→ Executor（验收驱动，可并行）→ Verifier（编译/契约/运行时/行为四层信号）→ Debugger（根因诊断与修复重派），Tester 按复杂度分档（S/M/L）启用；生成代码统一埋设语义化 data-testid 测试钩子。

## Requirements

### Requirement: 复杂度分档

功能实现节点 SHALL 按设计文档复杂度评估结果(S/M/L 三档)配置内部角色:每档至少包含 Planner 与 Executor;M 档及以上包含 Verifier;L 档增加 Tester 与 Debugger 及并行执行能力。

#### Scenario: S 档最小配置

- **WHEN** 设计文档评估为 S 档(如 ≤3 页面、简单表单)
- **THEN** 功能实现以 Planner + Executor 执行,验证仅做 L1 编译

#### Scenario: L 档完整配置

- **WHEN** 设计文档评估为 L 档(如多模块、含权限与 API 层)
- **THEN** 功能实现启用 Planner + Executor×N(并行)+ Verifier + Debugger + Tester

### Requirement: Planner 基于 Spec 拆解

Planner SHALL 依据架构 Spec 生成任务 DAG:目录树推导任务边界、数据模型推导接口契约、组件树推导依赖关系;任务粒度与 Spec 结构对应,不得使用与 Spec 无关的硬编码启发式。

#### Scenario: DAG 与 Spec 对齐

- **WHEN** Spec 的 directory_tree 声明了 router/ 与 stores/ 目录
- **THEN** Planner 输出的任务包含对应文件生成任务,且依赖关系符合 component_tree

### Requirement: Executor 验收驱动

每个 Executor 任务 SHALL 携带验收标准(文件清单、接口契约、编译要求),Executor 在任务完成时按验收标准自检;验收标准由 Planner 依据 Spec 生成。

#### Scenario: 契约验收

- **WHEN** 任务 contract 声明组件对外导出某函数,而 Executor 生成的文件未导出
- **THEN** 任务验收失败,进入失败处理流程

### Requirement: Verifier 四层验证信号

Verifier SHALL 按四层信号验证生成代码:L1 编译(esbuild 及前端 bundler 反馈)、L2 接口契约(exports/props/events 一致性)、L3 运行时(应用可启动、页面可渲染、无 console 错误)、L4 行为(测试执行,仅 L 档)。任一信号失败即验证失败,并提供证据。

#### Scenario: L1 编译失败

- **WHEN** 生成代码存在编译错误
- **THEN** Verifier 输出编译错误证据(file/line/message)并判定失败

#### Scenario: L3 运行时失败

- **WHEN** 应用启动后页面渲染报错或 console 存在未捕获异常
- **THEN** Verifier 输出运行时证据(错误信息、相关页面)并判定失败

#### Scenario: 四层全部通过

- **WHEN** 编译、契约、运行时、行为四层均通过
- **THEN** Verifier 判定成功,任务完成

### Requirement: Debugger 根因修复

任务或整体验证失败时,Debugger SHALL 基于证据链(编译错误、契约违约、运行时异常)定位根因,输出修复指令并重派对应任务;同一失败不得以相同方式重复执行。

#### Scenario: 契约违约修复

- **WHEN** 验证失败原因为两个文件间契约不一致
- **THEN** Debugger 定位违约双方,输出修复指令,重派受影响任务

#### Scenario: 无进展检测

- **WHEN** 同一任务连续修复后仍失败且证据未变化
- **THEN** Debugger 判定无进展,升级为 Manager 恢复决策(拆分或回退)

### Requirement: 测试钩子埋点

功能实现节点 SHALL 在生成代码时,为关键交互元素(按钮、输入框、分页、导航等)统一埋设语义化 `data-testid` 钩子,钩子名使用 kebab-case。

#### Scenario: 关键元素埋点

- **WHEN** Executor 生成含"保存按钮"的页面代码
- **THEN** 该按钮 DOM 包含 `data-testid="save-button"` 类语义化钩子

#### Scenario: 钩子作为验收项

- **WHEN** Verifier 执行 L1/L2 验证
- **THEN** 关键交互元素缺少 data-testid 视为验证失败项
