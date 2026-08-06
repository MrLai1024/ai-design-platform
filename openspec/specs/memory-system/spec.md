# memory-system Specification

## Purpose

四层记忆系统：短期 run_context、中期运行轨迹与问题记录（按 generation 归档）、长期用户级（服务端偏好与失败模式）、长期应用级（随代码仓 `.ai-memory/` 目录）。应用记忆生成期持续写入，兼作崩溃恢复检查点；增量开发时加载应用记忆、diff 新需求并产出变更 manifest。

## Requirements

### Requirement: 四层记忆

系统 SHALL 提供四层记忆:短期(run_context,本次运行状态)、中期(运行轨迹与问题记录,按 generation 归档)、长期用户级(服务端存储的用户偏好与通用失败模式)、长期应用级(随代码仓的 `.ai-memory/` 目录)。Manager 为四层记忆的唯一读写者,worker 仅通过分发上下文获取所需信息。

#### Scenario: 长期用户级记忆跨应用生效

- **WHEN** 用户在新一轮生成中提出需求,且其历史偏好记录了常用组件库
- **THEN** Manager 将该偏好作为约束写入分发与澄清上下文

#### Scenario: worker 无权读写记忆

- **WHEN** 某 worker 尝试访问其他 generation 的轨迹记录
- **THEN** 访问被拒绝,worker 只能读取分发上下文

### Requirement: 应用记忆目录结构

长期应用级记忆 SHALL 以 `.ai-memory/` 目录存放于生成应用根目录,包含 index.json、spec/(requirements.md、architecture.json、architecture.md、decisions.md)、state/(state.json、contracts.json)、changes/ 与 problems.jsonl。

#### Scenario: 记忆目录生成

- **WHEN** 生成应用初始化完成
- **THEN** 应用根目录存在 `.ai-memory/` 目录及 index.json 清单文件

#### Scenario: 架构 Spec 复用

- **WHEN** 方案设计节点产出架构 Spec
- **THEN** 同一份 Spec 写入 `.ai-memory/spec/architecture.json`,不维护第二套格式

### Requirement: 生成期持续写入

应用记忆 SHALL 在生成过程中持续写入(节点完成写 spec、把关决策写 decisions、问题修复写 problems.jsonl),而非保存时才写入。

#### Scenario: 节点完成后落盘

- **WHEN** 需求分析节点完成
- **THEN** 全量需求规格写入 `.ai-memory/spec/requirements.md`

#### Scenario: 问题修复留痕

- **WHEN** 某失败经诊断修复闭环
- **THEN** problems.jsonl 追加该问题、根因与修复策略记录

### Requirement: 崩溃恢复检查点

系统 SHALL 以应用记忆为崩溃恢复检查点:进程崩溃或用户取消后,重新启动 SHALL 依据 `.ai-memory/` 恢复(已完成节点跳过、进行中节点续跑)。

#### Scenario: 崩溃后恢复

- **WHEN** 代码节点生成过程中进程崩溃,重启后再次发起同一 generation
- **THEN** 系统从 `.ai-memory/` 识别已完成阶段并从中断处续跑

### Requirement: 增量开发加载

对已有应用发起增量开发时,系统 SHALL 加载应用记忆:state.json 与 decisions.md 全量加载,requirements.md 与 architecture.json 加载摘要并支持按需检索;新需求与现有规格做 diff,产出变更清单。

#### Scenario: 增量需求 diff

- **WHEN** 用户对已有应用提出新需求
- **THEN** 系统输出新增/修改/删除的功能点清单,并以对话框消息呈现

### Requirement: 变更 manifest

增量开发 SHALL 以变更 manifest 声明变更类型(新增功能/行为变更/重构/视觉改版)、涉及模块与受影响需求点;manifest 由 Manager 判定并经用户确认。

#### Scenario: manifest 用户确认

- **WHEN** Manager 判定变更类型为行为变更并列出受影响需求点
- **THEN** 用户在对话框确认或修正后,增量流程继续

#### Scenario: 重构类型影响用例处置

- **WHEN** manifest 类型为重构(行为不变)
- **THEN** 历史用例按处置策略分类,keep 用例必须回归通过,fix-selector 用例修复选择器后回归

### Requirement: 历史用例处置与回归对账

增量开发的回归执行 SHALL 按用例状态对账:active 用例失败为真回归,expected_broken 用例失败符合预期;处置清单(keep/update/retire/fix-selector)经用户确认后执行。

#### Scenario: 处置清单呈现

- **WHEN** 增量开发涉及历史用例处置
- **THEN** Manager 在对话框呈现处置清单及理由,用户确认后执行回归

#### Scenario: active 用例失败

- **WHEN** 回归中某 active 用例失败且非预期失效
- **THEN** 按真实回归处理,证据进入诊断与修复流程
