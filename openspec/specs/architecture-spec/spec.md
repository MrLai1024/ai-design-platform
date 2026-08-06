# architecture-spec Specification

## Purpose

方案设计节点输出双产物：人读设计文档（Markdown）与机读架构 Spec（JSON）。架构 Spec 是整条流水线的公共接口——Manager 分层把关的检查对象、功能实现 Planner 拆解的输入、Verifier 的验收基准，字段缺失或与 PRD 不一致即把关不通过。

## Requirements

### Requirement: 方案设计节点输出双产物

方案设计节点 SHALL 输出两份产物:人读设计文档(Markdown)与机读架构 Spec(JSON);两者描述同一设计方案。

#### Scenario: 双产物输出

- **WHEN** 方案设计节点执行完成
- **THEN** 产物包含 design 文档与 architecture spec(JSON),且 spec 可通过 schema 校验

### Requirement: 架构 Spec 字段完整

架构 Spec SHALL 包含以下字段:tech_stack、directory_tree、data_model、api_contracts、routing、state_management、component_tree、pages、decisions;任一必需字段缺失或为空,Manager 的 L1 把关判定不通过。

#### Scenario: 字段缺失判不通过

- **WHEN** 方案设计节点回流 Spec 缺少 directory_tree
- **THEN** Manager L1 检查判定不通过,进入恢复流程

#### Scenario: 字段完整判通过

- **WHEN** 回流 Spec 全部必需字段非空且格式合法
- **THEN** L1 检查通过,进入 L2 一致性评估

### Requirement: Spec 与 PRD 一致性

Manager 的 L2 把关 SHALL 核对架构 Spec 与 PRD 功能点的对应关系;PRD 中的每个确认功能点都应在 Spec 的 pages 或 component_tree 中落地。

#### Scenario: 功能点遗漏

- **WHEN** PRD 包含功能点 R-05,但 Spec 的 pages/component_tree 中无对应实现条目
- **THEN** L2 判定不通过,并输出缺失清单作为重派反馈

#### Scenario: 功能点全落地

- **WHEN** Spec 覆盖 PRD 全部确认功能点
- **THEN** L2 判定通过

### Requirement: Spec 作为功能实现的输入

功能实现节点的 Planner SHALL 以架构 Spec 为唯一工程输入进行任务拆解,不得再从自由格式设计文档推断工程结构。

#### Scenario: Planner 消费 Spec

- **WHEN** 功能实现节点启动
- **THEN** Planner 依据 Spec 的 directory_tree 推导任务边界、data_model 推导契约、component_tree 推导依赖关系

### Requirement: Spec 作为验证基准

Verifier 对生成代码的验收 SHALL 以架构 Spec 为基准(目录结构存在性、API 契约、组件依赖),代码与 Spec 不一致处作为验证失败证据。

#### Scenario: 目录与 Spec 不符

- **WHEN** Verifier 检查生成代码目录,发现 Spec 声明的目录缺失
- **THEN** 验证失败,缺失目录作为证据进入 Debugger 诊断

### Requirement: 决策记录入 Spec

架构 Spec 的 decisions 字段 SHALL 记录关键技术选型及其理由(含用户在澄清阶段确认的方案选择),决策日志随 Spec 持久化。

#### Scenario: 用户选择写入决策

- **WHEN** 用户在澄清阶段选择了候选方案 B(如 element-plus + 多页应用)
- **THEN** Spec 的 decisions 包含该选择及理由,后续节点不得另行推翻该决策
