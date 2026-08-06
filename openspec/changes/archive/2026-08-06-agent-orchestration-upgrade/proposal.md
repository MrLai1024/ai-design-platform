## Why

当前 ai-generation-app 的 agent 编排是"硬编码规则 + 各管一段"的 5 节点直连流水线:每个节点只拿前一个节点的输出,没有任何 agent 见过完整的用户需求;需求澄清是固定三层提问;失败恢复只有"重试/回退固定节点",无法诊断根因、无法自主拆分闭环;状态全在内存,重启即失,也没有任何跨会话记忆。生成的产物无法沉淀,应用无法增量开发。

## What Changes

- **BREAKING** 编排形态从"节点直连流水线"改为 **manager-worker 多 Agent 系统**:1 个全局协调 Agent(Manager)分发任务给 4 个专业子 Agent 系统(需求分析/方案设计/功能实现/E2E),所有 worker 结果回流 Manager 把关,产物不直传。
- **左侧对话框即全局 Agent 的人格**:头脑风暴主持、节点结果摘要、把关裁决、失败求援全部以结构化消息(question/proposal/summary/verdict/diagnosis/confirm/coverage)呈现在对话框中;worker 不与用户直接对话。
- 流水线改为 **头脑风暴 → 需求分析 → 方案设计 → 功能实现 → E2E**,**BREAKING** 删除质量校验节点(review),其职责拆分到 Manager 分层把关与实现节点内部验证。
- **头脑风暴**:从固定三层提问升级为议程驱动的探索式澄清(议程项=待澄清项+缺失后果,用户未答项标注为假设)+ 候选方案对比(范围取舍/交互形态,技术栈粗粒度)。
- **方案设计节点输出结构化架构 Spec**(JSON schema:技术栈/目录树/数据模型/API契约/路由/状态管理/组件树/页面),作为 Manager 把关与功能实现拆解的公共接口;附人读设计文档。
- **功能实现节点**重构为内部多角色系统:Planner(Spec→DAG)+ Executor×N(契约+验收驱动,可并行)+ Verifier(编译/契约/运行时/行为四层信号)+ Debugger(根因诊断→修复指令),Tester(单测/组件测试)按复杂度分档启用(S/M/L)。
- **E2E 节点**重构为 Test Designer + Test Runner + Test Diagnoser 双 agent 系统:需求点→覆盖矩阵→结构化 DSL 用例;选择器以 data-testid/文本/role 优先;失败三方诊断(真回归/预期失效/选择器耦合)。
- **四层记忆系统**:短期 run_context + 中期运行轨迹/问题记录 + 长期用户级(服务端,偏好/失败模式)+ 长期应用级(随代码仓 `.ai-memory/`,全量规格/架构Spec/决策日志/功能状态/接口契约/问题史/变更记录)。应用记忆生成期持续写入,兼作崩溃恢复 checkpoint。
- **增量开发工作流**:加载应用记忆 → 新需求 vs 现有规格 diff → 变更 manifest(新增/行为变更/重构/视觉,用户确认)→ 增量流水线 → 旧用例回归+新用例 → 更新应用记忆。重构时按 manifest 对历史用例处置(keep/update/retire/fix-selector),用例文件入库随代码版本化。
- **自主闭环**:失败分类(LLM错/格式/编译/跑偏/矛盾/无收敛)→ 诊断 → 重派/拆分/回退/上报;红线:每个问题自主闭环 ≤2 轮,之后对话框汇报并给出"继续自主/转人工"选项;不得自主修改需求范围。

## Capabilities

### New Capabilities

- `coordinator-agent`: 全局协调 Agent — 任务分发(带验收标准)、分层把关(L1硬规则/L2每节点评估/L3跨节点)、对话框发言人格、意图路由
- `brainstorm-clarification`: 议程驱动的探索式需求澄清 + 候选方案对比 + 假设清单
- `architecture-spec`: 方案设计节点输出结构化架构 Spec(JSON schema + 人读文档)
- `function-implementation`: 功能实现节点内部多角色系统(Planner/Executor/Verifier/Debugger/Tester,复杂度分档 S/M/L)
- `e2e-verification`: E2E Test Designer/Runner/Diagnoser,需求覆盖矩阵 + 结构化 DSL + data-testid 钩子规范
- `memory-system`: 四层记忆 + `.ai-memory/` 应用记忆随仓走 + 增量开发工作流 + 变更 manifest
- `problem-recovery`: 失败分类诊断与自主闭环(恢复策略阶梯 + 红线规则 + 求援出口)

### Modified Capabilities

- `code-feedback-loop`: 用户反馈注入点从 Planner ReAct 循环迁移到 Manager 把关/重派决策,反馈内容进入问题记录与恢复闭环
- `compile-feedback`: 编译反馈从 Executor 唯一验证信号升级为 Verifier 四层信号中的 L1,并作为 Debugger 根因诊断的证据来源

## Impact

- **后端 ai-service**(Python):`app/services/generation/` — graph.py 重构为 supervisor 形态、nodes.py 按角色拆分、新增 coordinator/memory/e2e 模块、requirements/ 的固定三层提问替换为议程引擎;新增 `.ai-memory/` 读写与增量开发加载逻辑
- **前端 ai-generation-app**(Vue):ChatPanel 消息类型扩展(question/proposal/summary/verdict/diagnosis/confirm/coverage 卡片)、GenerationView 移除 review 面板、E2E 执行引擎升级(console/网络/等待条件/证据收集)、AgentLog 反馈入口迁移
- **接口层**(gRPC gateway/proto):可能新增头脑风暴对话、应用记忆加载/保存、变更 manifest 确认等 RPC 或复用现有 StreamGenerate 事件体系
- **删除**:review 节点及其前端 ReviewStagePanel、多 Agent 并行审查(安全/性能/可访问性/可维护性)
- **无外部服务依赖**:长期记忆起步用 SQLite,不引入向量库;E2E 引擎二期再评估后端浏览器
