## ADDED Requirements

### Requirement: 设计节点输出结构化架构 Spec

设计节点 SHALL 输出双产物：人读设计文档（Markdown）与机读架构 Spec（JSON），Spec 作为 Planner 拆解、验证与编译的公共基准。Spec 结构与定稿 schema 一致，包含 `spec_version`、`tech_stack`、`directory_tree`、`data_model`、`api_contracts`、`routing`、`state_management`、`component_tree`、`pages`、`decisions` 十个字段。

#### Scenario: 设计完成后双产物可用

- **WHEN** 设计节点完成生成
- **THEN** 状态中同时存在 `design_doc`（人读 MD）与结构化 `architecture_spec`（JSON 对象），且字段齐全

#### Scenario: Spec 与设计文档内容一致

- **WHEN** 设计文档声明了页面与组件
- **THEN** Spec 的 `pages` 与 `component_tree` 反映相同结构，数据实体进入 `data_model`，接口进入 `api_contracts`

### Requirement: Spec 字段确定性校验

设计节点 SHALL 在产出 Spec 后执行确定性校验（零 LLM）：必填字段齐全、字段类型正确（`data_model`/`api_contracts`/`routing`/`component_tree`/`pages`/`decisions` 为数组，其余为对象）。

#### Scenario: 字段完整校验通过

- **WHEN** Spec 十个必填字段均非空且类型正确
- **THEN** 校验通过，Spec 进入下游环节

#### Scenario: 字段缺失触发修复

- **WHEN** Spec 存在缺失字段或类型错误
- **THEN** 校验失败，设计节点依据校验错误重新生成缺失部分后再次校验

### Requirement: LLM 输出解析降级兜底

当设计节点的 LLM 输出无法解析为符合 schema 的 JSON 时，系统 SHALL 以 schema 形状的空默认值做类型强制合并，保证下游拿到结构完整的 Spec 而非原始文本。

#### Scenario: JSON 解析失败兜底

- **WHEN** 设计节点 LLM 输出包含无效 JSON 或缺失大部分字段
- **THEN** Spec 以空默认结构兜底生成，并在日志记录解析失败，设计节点重试一次

### Requirement: Planner 以 Spec 为唯一拆解输入

功能实现节点的 Planner SHALL 基于架构 Spec 生成任务 DAG：`directory_tree` 推导任务边界与文件归属、`data_model` 推导接口契约、`component_tree` 推导任务依赖关系，不得使用与 Spec 无关的硬编码启发式（如固定 bootstrap 任务数量或文件数上限）。

#### Scenario: DAG 与 Spec 对齐

- **WHEN** Spec 的 `directory_tree` 声明了 `src/router/` 与 `src/stores/` 目录
- **THEN** Planner 输出包含对应文件的生成任务，且任务依赖符合 `component_tree` 声明

#### Scenario: 无 Spec 时不产出硬编码 DAG

- **WHEN** 状态中不存在架构 Spec
- **THEN** 功能实现节点不进入拆解流程，要求先完成设计节点
