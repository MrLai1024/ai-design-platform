## Context

当前 ai-generation-app 的编排实现在 `ai-service/app/services/generation/`:

- **graph.py**: LangGraph 5 节点直连流水线 `analysis → design → code → review → e2e`,条件边做回退(review 失败→code/design,e2e 失败→code),`interrupt_before` 在 code/review/e2e 前暂停等用户确认;`MemorySaver` 检查点全在内存。
- **requirements/**: 固定三层提问状态机(vision → features → details),层完成靠规则/LLM 自评,无方案对比。
- **nodes.py**: code 节点 = Planner(DAG,硬编码"3 bootstrap/≤5 文件"启发式)→ Executor(ReAct,验证信号只有 esbuild 编译)→ Reflect(失败任务重跑一次)。
- **前端**: 左侧 ChatPanel 用独立 chat 模式做澄清(prompt 写死"3+ 轮后准备就绪"),节点确认靠右侧"下一步"按钮;review 面板为 4 维并行质量审查。

痛点(经与用户多轮探索确认):无全局把关、无跑偏检测、澄清固定化、失败恢复无诊断、状态不持久、零跨会话记忆、无法增量开发。本设计将编排升级为 **manager-worker 多 Agent 系统 + 四层记忆**。

## Goals / Non-Goals

**Goals:**

1. 全局协调 Agent(Manager)作为唯一与用户对话的存在(左侧对话框即其人格),分发任务、分层把关、失败恢复决策。
2. 5 阶段流水线:头脑风暴(议程驱动)→ 需求分析(PRD)→ 方案设计(架构 Spec)→ 功能实现(多角色)→ E2E(双 agent);删除 review 节点。
3. 方案设计节点产出结构化架构 Spec,作为把关与实现拆解的公共接口。
4. 四层记忆;应用记忆(`.ai-memory/`)随代码仓走,支撑增量开发与崩溃恢复。
5. 失败分类 → 诊断 → 自主闭环(重派/拆分/回退/上报),红线可控。

**Non-Goals:**

- 不引入向量库/embedding(长期记忆检索用结构化表 + 关键词,向量化后置)。
- E2E 后端真浏览器执行(Playwright)一期不做,复杂用例标注 `requires_browser` 后置。
- 不做模型路由(Planner/Executor 按复杂度选模型)与任务动态并行调度优化;复杂度分档仅做角色配置,不重排执行引擎。
- review 节点删除后的安全/性能纵深审查不做替代能力。
- 服务端"应用资产列表/跨应用搜索"不在一期(随后续代码仓功能一起设计)。
- 需求澄清的 edit/append 进入模式一期保留"新需求"与"继续澄清",edit/append 后置。

## Decisions

### D1. 编排形态:Manager-Worker(Supervisor 风格 LangGraph)

**决策**:保留 LangGraph 作骨架,graph 重构为 supervisor 形态 — 每个 worker 节点执行后条件边必回 `manager_gate` 节点;`manager_gate` 完成把关裁决 + 记忆写入后,条件边路由到下一个 worker(或回退、或拆分派发、或结束)。worker 间不直连,产物全部经 Manager 回流。

**备选**:纯自定义 asyncio 编排循环(放弃 LangGraph 的 checkpoint/interrupt/streaming 能力)— 否决;对话中枢形态(Manager 主循环,节点变函数调用)— 否决(长耗时/流式/恢复塞进对话上下文,工程重)。

### D2. 对话人格:对话框 = Manager,消息类型化

**决策**:Manager 是唯一发言者。对话框消息扩展为结构化类型:

| 类型 | 内容 | 用户交互 |
|---|---|---|
| text | 澄清问题/解释/求援 | 文本回复 |
| question_card | 问题+选项(单选/多选) | 点选项(升级现有按钮) |
| proposal_card | 候选方案 2~3 个+优劣 | 选择/混合/都不要 |
| summary_card | 节点完成摘要 | 审阅右侧产物 |
| verdict_card | 把关结果(通过/回退+原因) | 追问/确认 |
| diagnosis_card | 失败诊断+恢复策略+进度 | 继续自主/转人工 |
| confirm_card | 需用户拍板(假设/范围/确认) | 接受/拒绝/修改 |
| coverage_matrix | E2E 需求覆盖矩阵 | 确认执行/补充用例 |

**意图路由**:用户对话框输入三类意图(澄清回答/流程指令/产出反馈),由 Manager 每次轻量 LLM 调用自判,不设前端规则分流。

**节点确认**:右侧产物区保留"下一步"操作,对话框负责叙事(节点完成时 Manager 先发 summary_card)。

### D3. 把关:分层 + 分发时下发验收标准

**决策**:每次分发 `dispatch = {task_id, 输入引用, 验收标准, 工具边界, 约束}`;worker 完成回流后,Manager 按分发时承诺的验收标准裁决:

- **L1 硬规则**(确定性,零 LLM):编译/结构/JSON 格式/契约字段完整 — 由现有 `EvalHarness` 升级。
- **L2 每节点评估**(Manager LLM 判断):PRD↔澄清确认项覆盖矩阵、Spec↔PRD 功能点一一对应、代码↔Spec 目录树/契约核对。
- **L3 跨节点**(Manager LLM 判断):需求→方案→实现整体一致性、跑偏检测。

重活(如 Spec 与代码的逐文件核对)可派轻量 evaluator worker,但**决策权在 Manager**。

### D4. 头脑风暴:议程驱动的探索式澄清

**决策**:替换 requirements/ 固定三层状态机。核心状态为**澄清议程**:

```
AgendaItem = { id, topic, reason(缺失后果), impact(影响面),
               status: answered|assumed|conflict, answer }
```

- 首轮:Manager 主动分析(需求类型识别/模糊点识别/候选方案雏形),不提问。
- 每轮:按"对后续节点影响"排序问 1~3 个问题;未答项标 `assumed`,PRD 中集中呈现"假设清单"。
- 收敛前最后一轮:**方案对比**(范围取舍 + 交互形态,各带优点/代价;技术栈问粗粒度如微前端 vs 单应用),选择结果进决策日志。
- 退出条件双因子:议程覆盖度 ≥ 阈值 **且** 用户确认收敛(替代现有 LLM 自评分)。
- 产出:`RequirementsState`(议程确认项)+ 决策日志 + 假设清单。

**备选**:保留三层固定提问,仅改 prompt — 否决(简单需求过度提问、复杂需求问不透、无方案对比)。

### D5. 方案设计节点 = 架构脑:输出架构 Spec(JSON schema)

**决策**:方案设计节点输出双产物 — 人读设计文档(MD)+ 机读架构 Spec(JSON)。Spec 是整条流水线的公共接口:Manager 把关的检查对象、Planner 拆解的输入、Verifier 的验收基准。Schema 定稿如下(方案设计节点的输出契约):

```jsonc
{
  "spec_version": 1,
  "tech_stack": { "framework": "vue3", "component_lib": "element-plus",
                  "build": "webpack", "style": "scss" },
  "directory_tree": { "src/": ["main.ts", "App.vue", "router/", "components/",
                               "stores/", "api/"] },
  "data_model": [ { "name": "User", "fields": [{ "name": "id", "type": "string" }] } ],
  "api_contracts": [ { "name": "user/list", "method": "GET",
                       "request": {}, "response": {} } ],
  "routing": [ { "path": "/", "page": "Home", "auth": false } ],
  "state_management": { "store": "pinia", "stores": ["user", "cart"] },
  "component_tree": [ { "name": "Header", "uses": ["NavMenu"], "props": [] } ],
  "pages": [ { "id": "p-01", "name": "登录页", "interactions": [], "data": [] } ],
  "decisions": [ { "topic": "技术选型", "choice": "element-plus", "reason": "用户选择" } ]
}
```

**粒度**:S/M 档直接单次生成;L 档允许两步(选型+总体架构 → 细化 Spec)。

### D6. 功能实现节点:内部多角色系统,复杂度分档

**决策**:功能实现节点 = 内部 manager-worker(Engineering Lead 管理),角色配置按设计文档复杂度自适应:

| 档位 | 判定线索(页面数/数据实体/权限) | 角色配置 |
|---|---|---|
| S | ≤3 页面、简单表单 | Planner + Executor |
| M | 多页面、数据流/状态管理 | + Verifier(L1~L3 信号) |
| L | 多模块、权限、API 层 | + Tester(TDD)+ Debugger + 并行 Executor |

角色职责与差距修复映射:

- **Planner**:Spec→DAG(目录树→task 边界、数据模型→契约、组件树→依赖);不再硬编码 bootstrap 启发式,从 Spec 的 directory_tree 推导工程任务。
- **Executor ×N**:单任务 ReAct,任务级验收标准 = 契约(expects/provides)+ 编译 + 文件清单;L 档无依赖任务并行。
- **Verifier**:四层信号 L1 编译(esbuild+前端 bundler 实时反馈,现有 compile-feedback 流程保留)/ L2 契约(`verify_contract` 工具接入循环,不再闲置)/ L3 运行时(dev server + console + 页面渲染,前端 sandbox 提供)/ L4 行为(单测/组件测试,仅 L 档)。
- **Debugger**:失败证据链(错误定位→文件→修复指令)→ 重派;替代现有"失败任务重跑一次"。
- **Tester**(L 档):验收先行生成单测/组件测试并执行。

**备选**:单 agent 长上下文全仓实现(Cursor/Claude Code 风格)— 对几十文件整仓生成不并行、易漂移;现两段式 — 缺验证/调试/测试,已确认不足。

### D7. E2E 节点:双 agent + 覆盖矩阵 + 结构化 DSL + 诊断闭环

**决策**:

- **Test Designer**:输入 = PRD 需求点清单(澄清/PRD 阶段结构化产物)+ Spec 页面清单 → 输出**覆盖矩阵**(需求点→用例映射,每个需求点 ≥1 用例为通过门禁)+ 结构化 DSL 用例(非 Markdown)。
- **用例 DSL**:

```jsonc
{ "id": "tc-r03-1", "requirement_id": "R-03", "scenario": "分页切换",
  "steps": [{ "action": "click", "target": { "by": "testid", "value": "pagination-next" } },
            { "action": "assert", "target": { "by": "text", "value": "第 2 页" },
              "assertion": "contains" }] }
```

- **选择器规范(跨节点约定)**:功能实现节点生成代码时给关键交互元素统一埋 `data-testid`(钩子名 = 语义化 kebab-case);用例选择器优先 `testid` → `text` → `role` → `css`(css 仅兜底)。
- **Test Runner**:前端 iframe 沙箱执行(一期),升级点:console 错误注入监听、网络请求监听、MutationObserver/等待条件、真实渲染截图。复杂用例(多页流转/登录态)标 `requires_browser: true` 一期跳过或人工,二期接后端浏览器。
- **Test Diagnoser**:失败三方分类 — 断言不符+manifest 声明行为变更 → 预期失效(改写用例);元素缺失+DOM 变+行为没变 → 选择器耦合(修钩子/换选择器);行为真坏 → 回功能实现节点。证据:DOM 快照 + console 日志 + 截图。
- **用例文件入库**:`e2e/cases/*.json` + `e2e/manifest.json` 写入生成仓,随代码版本化。

### D8. 四层记忆

```
① 短期 run_context   本次运行: 议程/产物引用/验收记录 (内存,写透到④暂存区)
② 中期 运行轨迹       事件流摘要/问题记录/修复过程 (结构化表,按 generation 归档)
③ 长期-用户 服务端    用户偏好/通用失败模式/修复策略 (SQLite,挂 user 维度)
④ 长期-应用 随仓      .ai-memory/ 目录 (见下)
```

**④ 应用记忆目录结构**(随代码仓,git 友好,Markdown+JSON):

```
my-app/.ai-memory/
├── index.json              # 清单/版本指针/应用元信息
├── spec/requirements.md    # 全量需求规格(PRD + 假设清单)
├── spec/architecture.json  # 架构 Spec(与 D5 schema 同构,直接复用)
├── spec/architecture.md    # 人读设计文档
├── spec/decisions.md       # 决策日志(方案对比/取舍理由)
├── state/state.json        # 功能状态: 已实现/未实现/里程碑
├── state/contracts.json    # 文件接口契约(现有 context_summary 持久化)
├── changes/                # 增量开发变更记录(每次一个文件)
└── problems.jsonl          # 问题→根因→修复策略(时间线)
```

**写入时机**:生成期持续写(节点完成写 spec、把关写 decisions、修复写 problems.jsonl),而非保存时才写 — 兼作崩溃恢复 checkpoint:进程崩溃/取消后从 `.ai-memory` 恢复(已完成节点跳过,进行中节点续跑)。实现上 ai-service 把 project_root 从 `tempfile.gettempdir()` 迁移到持久目录(如 `data/generated/<app_id>/`),`report_compile_feedback` 等运行时状态随之持久化。

**加载策略(增量开发)**:`state.json` + `decisions.md` 全量加载(小);`requirements.md`/`architecture.json` 加载摘要,细节按需检索。

### D9. 增量开发工作流 + 变更 manifest

**决策**:

```
加载应用记忆 → 新需求 diff(新增/修改/删除) → 变更 manifest → 影响分析
  → 增量流水线(增量PRD → 增量设计 → 只动受影响模块实现) → 回归+新用例 → 更新记忆
```

**变更 manifest**(增量开发第一产物,Manager 自动判定 + 对话框用户确认):

```jsonc
{ "change_id": "chg-2026-08-03-001",
  "type": "new_feature | behavior_change | refactor | visual",
  "affected_modules": ["Header", "DataTable"],
  "affected_requirement_points": ["R-03"],
  "behavior_changes": [ { "point": "R-03", "from": "客户端分页", "to": "服务端分页" } ] }
```

**历史用例处置**(Test Impact 分析,随 E2E 系统执行):对每个旧用例打 `keep / update / retire / fix-selector`;处置清单对话框展示给用户确认。回归报告按用例状态对账(`active` 红 = 真回归;`expected_broken` 红 = 符合预期)。用例文件本身入库版本化,重构时代码与用例同批更新。

### D10. 自主闭环与红线

**决策**:失败分类(LLM 调用错误/输出格式非法/编译失败/内容跑偏/前后矛盾/无收敛)→ 诊断根因 → 恢复阶梯:

```
重派(带反馈回同一 worker) → 拆分(并行派发子任务) → 回退(更早节点) → 上报(转人工)
```

红线规则(写进 Manager 决策约束):

- 每个问题自主闭环 ≤ 2 轮;之后必须对话框 `diagnosis_card` 汇报,提供"继续自主 / 转人工"选项。
- **不得自主修改需求范围**;范围变更一律 confirm_card 问用户。
- 沿用并扩展现有 `LoopControl`:每节点回退 ≤3 次、总数 ≤10、无改进检测;超限转求援。

## Risks / Trade-offs

- [Manager 单点瓶颈/对话上下文膨胀] → 节点产物不进对话上下文,Manager 只持摘要与验收记录;产物经 run_context 引用。
- [supervisor 形态增加 LLM 调用次数(每节点多一次把关)] → L1 硬规则零成本先行;L2/L3 把关 prompt 限定输出 schema;S 档可降级为轻量检查。
- [议程驱动澄清可能问不满/问过头] → 双因子退出 + 假设清单兜底;假设项在 PRD 中集中可见可纠。
- [data-testid 埋点遗漏导致用例脆弱] → 选择器降级链 css 兜底 + Diagnoser 选择器耦合分类 + fix-selector 处置;testid 埋点作为功能实现节点的验收标准之一。
- [前端沙箱 E2E 能力边界] → 复杂用例标 `requires_browser` 明确跳过/人工,不硬撑;二期评估后端浏览器。
- [`.ai-memory/` 与代码漂移] → contracts.json 由生成过程维护,增量开发加载时重新核对生成物与记忆的一致性,不一致以代码为准并告警。
- [增量开发"重构"被误判为行为变更] → manifest 由用户确认,Diagnoser 以 manifest 为准分类,决策留痕。
- [SQLite 长期记忆无向量检索] → 起步用结构化表+关键词;字段设计预留 embedding 列,向量化后置无迁移成本。

## Migration Plan

分期实施(范围决策):**v1** = manager-worker 骨架 + 头脑风暴议程 + 分层把关 + 对话框消息体系 + 三层记忆骨架(①②③)+ `.ai-memory/` 应用记忆与增量开发(④)+ E2E 设计(A 引擎);**v2** = 功能实现节点 M/L 档升级(Tester/并行/Debugger 全量);**v3** = 记忆向量化、E2E 后端浏览器、模型路由。

演进路径:

1. 后端先落地 manager_gate 骨架:graph.py 重构为 supervisor 形态,review 节点移除,对话消息事件类型扩展;旧前端保持兼容(消息降级为 text)。
2. 头脑风暴议程替换固定三层提问,前端 question_card 复用现有选项按钮 UI。
3. 方案设计节点输出 Spec schema;Planner 改为消费 Spec。
4. `.ai-memory/` 写入与加载;project_root 迁移到持久目录。
5. E2E 双 agent 与用例入库。
6. 增量开发入口(加载已有应用)与变更 manifest。

回滚:graph 保留旧的直连拓扑作为配置开关;`.ai-memory` 为附加目录,不影响既有生成流程。

## Open Questions

- 议程覆盖度阈值与首轮需求类型分类的 prompt 细节(实现期定稿)。
- L 档并行 Executor 的文件冲突规避(契约校验之外是否需要锁/临时目录)。
- 应用记忆的 `state.json` 功能状态如何与生成过程保持原子更新(单写者假设 vs 文件锁)。
