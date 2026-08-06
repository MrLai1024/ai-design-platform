## 1. 编排骨架重构(manager-worker)

- [x] 1.1 重构 `graph.py`:流水线改为 头脑风暴→分析→设计→实现→E2E,删除 review 节点及其条件边
- [x] 1.2 新增 `manager_gate` 节点:worker 节点执行后条件边必回该节点,裁决后路由下一 worker(或回退/结束)
- [x] 1.3 移除 ReviewStagePanel/多 Agent 并行审查相关代码(review_node、REVIEW_AGENTS、_build_review_html)
- [x] 1.4 定义 dispatch 数据结构(task_id/输入引用/验收标准/工具边界/约束),servicer.py 初始化 state 时填充
- [x] 1.5 `interrupt_before` 调整:用户确认点改为 头脑风暴收敛、每节点把关通过后

## 2. Manager 对话人格与消息体系

- [x] 2.1 后端事件类型扩展:summary_card/verdict_card/diagnosis_card/confirm_card/proposal_card/coverage_matrix 的 GraphEvent 产出
- [x] 2.2 前端 ChatPanel 新增结构化消息卡片渲染(基于消息 meta 类型分流,现有选项按钮升级为 question_card)
- [x] 2.3 前端意图路由:Manager 自判接口(轻量 LLM 调用输出 reply_qa/proceed/feedback/escalate/ask_why)
- [x] 2.4 把关裁决消息:Manager 节点通过时输出 summary_card+verdict_card,失败时输出 diagnosis_card
- [x] 2.5 `needs_manual_review` 从右侧 banner 迁移为对话框求援消息(诊断+继续自主/转人工选项)

## 3. 头脑风暴议程引擎

- [x] 3.1 定义 AgendaItem 数据模型与议程状态(answered/assumed/conflict),替换 requirements/ 固定三层状态机的层推进逻辑
- [x] 3.2 首轮需求画像:需求类型识别 + 模糊点识别 + 候选方案雏形生成(结构化输出)
- [x] 3.3 每轮提问:按影响面排序选 1~3 个议程项,未答项标 assumed
- [x] 3.4 方案对比卡片:2~3 候选方案(范围取舍/交互形态)+ 优点代价,选择写决策日志
- [x] 3.5 双因子收敛:议程覆盖度计算 + 用户确认;收敛产物 = 结构化需求 + 决策日志 + 假设清单
- [x] 3.6 PRD 生成(analysis_node)改为消费澄清产物,新增"假设清单"章节

## 4. 方案设计节点:架构 Spec

- [x] 4.1 定义架构 Spec JSON schema(spec_version/tech_stack/directory_tree/data_model/api_contracts/routing/state_management/component_tree/pages/decisions)
- [x] 4.2 design_node 改为双产物输出:人读 MD + 机读 Spec(结构化输出强制 schema 校验)
- [x] 4.3 L1 把关:Spec 必需字段完整性校验(确定性检查,接入 EvalHarness)
- [x] 4.4 L2 把关:Spec 与 PRD 功能点覆盖核对(Manager LLM 判断,输出缺失清单)
- [x] 4.5 Spec 写入应用记忆 `.ai-memory/spec/architecture.json`(与任务 7 协同)

## 5. 功能实现节点改造

- [x] 5.1 复杂度分档评估:S/M/L 判定(页面数/数据实体/权限线索),角色配置进 dispatch
- [x] 5.2 Planner 改为消费架构 Spec:目录树→任务边界、数据模型→契约、组件树→依赖;移除硬编码 bootstrap 启发式
- [x] 5.3 Executor 任务级验收标准(文件清单+契约+编译)落地,`verify_contract` 接入执行循环
- [x] 5.4 Verifier 四层信号:L1 编译(复用 compile-feedback)/L2 契约/L3 运行时(前端 sandbox 提供 dev 运行与 console 收集)
- [x] 5.5 Debugger:证据链(错误→定位→修复指令)→重派;无进展检测
- [x] 5.6 L 档:并行 Executor(无依赖任务并发)+ Tester(单测/组件测试生成与执行)
- [x] 5.7 代码生成强制 data-testid 埋点(关键交互元素),埋点缺失作为验证失败项

## 6. E2E 节点重构

- [x] 6.1 Test Designer:需求点清单→覆盖矩阵→结构化 DSL 用例(JSON schema + 校验)
- [x] 6.2 选择器规范:testid→text→role→css 优先级生成逻辑
- [x] 6.3 执行引擎升级:console/网络监听、等待条件(MutationObserver 轮询)、渲染截图、DOM 快照证据
- [x] 6.4 Test Diagnoser:三方分类(预期失效/选择器耦合/真回归),依据 manifest 与证据
- [x] 6.5 覆盖矩阵门禁:需求点无用例→矩阵未通过;覆盖矩阵以 coverage_matrix 卡片呈现
- [x] 6.6 用例入库:`e2e/cases/*.json` + manifest.json(状态字段 active/expected_broken/archived)写入生成仓
- [x] 6.7 复杂用例 `requires_browser` 标注与跳过逻辑(一期),人工执行清单输出

## 7. 记忆系统

- [x] 7.1 project_root 从 `tempfile.gettempdir()` 迁移到持久目录(`data/generated/<app_id>/`),运行时状态随之持久化
- [x] 7.2 `.ai-memory/` 目录结构落地(index.json/spec/state/changes/problems.jsonl)
- [x] 7.3 生成期持续写入:节点完成写 spec、把关写 decisions、修复写 problems.jsonl
- [x] 7.4 短期记忆 run_context 定义与写透到应用记忆暂存区
- [x] 7.5 中期记忆:运行轨迹/问题记录结构化表(按 generation 归档,SQLite)
- [x] 7.6 长期用户级记忆:SQLite 表(偏好/失败模式/修复策略),挂 user 维度,Manager 启动时加载
- [x] 7.7 崩溃恢复:依据 `.ai-memory/` 恢复(已完成跳过、进行中续跑)
- [x] 7.8 增量加载策略:state.json/decisions 全量 + requirements/architecture 摘要 + 按需检索

## 8. 增量开发工作流

- [x] 8.1 已有应用入口:加载应用记忆→新需求 diff(新增/修改/删除功能点清单)
- [x] 8.2 变更 manifest 生成与用户确认(类型/涉及模块/受影响需求点/行为变更清单)
- [x] 8.3 增量流水线:增量 PRD→增量设计→只动受影响模块实现
- [x] 8.4 历史用例处置:Test Impact 分析(keep/update/retire/fix-selector)+ 处置清单对话框确认
- [x] 8.5 回归对账:按用例状态对账(active 红=真回归,expected_broken 红=预期),结果入 changes/ 记录
- [x] 8.6 记忆更新:changes/ 新增变更记录,state.json 功能状态推进

## 9. 问题闭环与恢复

- [x] 9.1 失败分类器:LLM错/格式非法/编译/跑偏/矛盾/无收敛(结构化输出)
- [x] 9.2 恢复阶梯实现:重派(带反馈)→拆分(并行子任务派发)→回退→上报
- [x] 9.3 红线规则:每问题自主 ≤2 轮后强制汇报;范围变更必须 confirm_card
- [x] 9.4 LoopControl 扩展:单节点 3 次/总数 10 次/无改进熔断,超限转求援
- [x] 9.5 problems.jsonl 写入与增量开发时历史修复策略检索复用

## 10. 反馈链路迁移

- [x] 10.1 `POST /api/v1/generation/feedback` 注入点从 Planner 迁移到 Manager 恢复决策,反馈入问题记录
- [x] 10.2 前端 AgentLog 反馈入口保留,处置结果改由对话框卡片呈现(折叠摘要)
- [x] 10.3 编译反馈消费方从 Executor 迁移到 Verifier(L1)+ Debugger(证据)
- [x] 10.4 新增运行时错误上报(console/未捕获异常/网络失败,关联 generation_id),供 Verifier L3 与 Diagnoser 使用

## 11. 验证与回归

- [x] 11.1 按 9 个 spec 的场景逐条核对实现(每条场景一个可执行验证)
      → `spec-traceability.md`(86 场景全映射)+ `tests/test_spec_traceability.py`
      (程序化守卫: 场景解析 × 矩阵 × 测试存在性 × worker 无记忆访问静态断言)
- [x] 11.2 端到端:新需求全流程(头脑风暴→PRD→Spec→实现→E2E)跑通,验证对话框消息完整
      → `tests/test_e2e_full_flow.py`(卡片序列 + 记忆产物 + 终裁 END)
- [x] 11.3 端到端:失败注入验证(编译错/跑偏/中断)走通恢复阶梯与红线
      → `tests/test_failure_injection.py`((a) 编译错→Debugger 修复闭环;
      (b) 同证据→无进展→求援红线→继续自主→通过; (c) 设计漂移→L2 重做→
      带反馈重生成; (d) 中断→由 11.5 覆盖)
- [x] 11.4 增量开发演练:已有应用加功能→diff→manifest→回归对账
      → `tests/test_incremental_drill.py`(存量文件不动 + changes/ 记录 +
      state.json 推进 + index 版本)
- [x] 11.5 崩溃恢复演练:代码节点中断后重启恢复
      → `tests/test_crash_recovery_drill.py`(index 阶段恢复 + 跳过已完成 +
      代码阶段续跑 + 产物一致)
