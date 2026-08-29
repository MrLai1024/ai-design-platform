## Why

功能开发节点的用户反馈链路是断的。用户在工程文件下方的输入框输入"继续"、"需要修改 xx 文件"后:

1. **agent 看不到工程现场** — feedback 触发前端 `confirmStage` fresh-start,servicer 重建**全新 state**:`generated_files = {}`(planner 的"已生成文件"清单为空)、旧 Task DAG/失败任务/`missing_paths` 全丢、`compile_errors = None`。planner 的 code_feedback 分支只拿到"设计方案 + 反馈文本",凭猜修正 —— 它不知道已生成哪些文件、哪些文件编译失败、哪些任务失败过。数据其实就在 `code_result`(generated_files 的完整 JSON 序列化,prefill 已带回),但从未被反序列化利用。
2. **"继续"是死路或重跑** — "继续"作为 code_feedback 塞进 prompt,无语义分支:planner 对比"空文件清单 vs 设计文档"以为什么都没生成 → 要么输出完整 DAG 重跑全部,要么空 delta → graph.py `"Planner produced no tasks"` 直接报错。
3. **无对话反馈感** — AgentLog 只渲染状态条目(思考/工具调用/文件/编译),executor 每轮的正式回复(`content`)只用来检测 `__TASK_DONE__`,一个字都没发给前端。

已确认方向:**方案 A(最小手术)** —— feedback fresh-start 时恢复工程现场(code_result 反序列化 + 磁盘兜底 + 旧 runner 状态注入),planner 基于现场重新规划;同时把 executor 的正式回复作为 agent 对话消息流式展示,补上交互感。

## What Changes

- **反馈现场恢复**:feedback fresh-start 时 `state["generated_files"]` 从 `code_result` 反序列化恢复;`code_result` 为空时从持久化目录 `data/generated/<gid>/` 扫描磁盘兜底;从旧 runner(按 generation_id 存活)提取上次 `compile_errors` 与失败任务摘要注入新 state。
- **planner 基于现场反馈**:code_feedback 分支的 prompt 注入现场 —— 已生成文件清单(带大小)+ 上次编译错误 + 失败任务列表(id/描述/failure_kind/missing_paths),planner 基于事实输出 delta 任务而非猜。**不做关键字匹配**:"继续"/"需要修改 xx"等任何输入一律走同一路径 —— 现场信息到位后,agent 自然判断该做什么(补任务 / 修复 / 无需修改),不写 `if "继续" in feedback` 这类分支。
- **空 delta 容错(非语义分支,且不得掩盖解析失败)**:feedback 场景下 planner 输出空 delta 是合法结果(agent 基于现场判断"无需修改")—— 正常收尾而非 "Planner produced no tasks" 死路。这是鲁棒性处理,不是对特定输入的响应;无反馈的首次规划空 delta 仍照常报错(那是真死路)。**必须区分两种空 delta**:agent 明确输出空任务列表(reasoning 说明"无需修改")→ 容错收尾;增量 planner 输出**解析失败**(JSON 解析异常兜底为空)≠ agent 意图,不得静默收尾,照常报错。容错条件是"有反馈"这个事实本身,不匹配反馈内容。
- **agent 对话消息(全模型生成,零模板)**:executor 每轮正式回复(content)以 `agent_message` 事件流式发给前端,AgentLog 渲染为对话气泡 —— 展示的是模型真实输出的自然语言。**不插入任何模板回执/文案**:"收到反馈,正在分析"这类话由 agent 基于真实上下文自己说出来,禁止后端拼接固定字符串假装智能。
- **后端事件零口吻(文案归属的结构性保证)**:后端事件只携带结构化数据,不携带人类文案 —— 删除现有 planner_reflect / 修复循环事件里后端拼接的 `message`(如"发现 N 个未规划文件,增量重规划…"),只留 `decision` / `missing_files` / `failed_task_ids` / `errors` 等数据字段。文案归属:
  - **agent 对话**(对话气泡,100% 模型输出):executor 的 content、planner 的 reasoning —— 后端原样透传,零加工
  - **系统状态**(状态卡,UI 文案允许模板):compile_status、planner_reflect 等 —— 由**前端**按 `decision` 渲染结构化短描述(如 replan_missing_files → "增量重规划:缺 3 个文件"),归属天然清晰,后端不可能再出现"系统消息冒充 agent 说话"

## 设计原则（贯穿全部改动）

- **零硬编码行为**:反馈处理不匹配任何关键字("继续"/"修改"/…),所有输入走同一路径;agent 的下一步行为由其基于现场信息的自主判断决定。
- **零模板文案**:任何展示给用户的 agent 文本都来自模型输出(content / reasoning / message),后端不拼接"收到反馈…"等固定字符串。交互反馈的真实感来自模型基于真实上下文的自然表达,而非文案模板。
- **提示词模板 ≠ 输出文案模板**:系统提示词/任务 prompt 的结构允许模板化(每次相同的任务指令,如"输出 Task DAG JSON"),但模型的输出文本不得被后端拼接、替换或改写后展示。前者是工程结构,后者才是"假智能"。
- **后端事件零口吻**:后端事件字段 = 数据(decision/errors/files),不含人类文案;任何展示文案按归属渲染 —— 模型输出原样透传,系统状态由前端 UI 层模板渲染。后端不拼接句子,结构性杜绝"系统消息冒充 agent 说话"。
- **鲁棒性 ≠ 语义**:空 delta 容错是防御性处理(防死路),不是"空输入→无事发生"的行为分支;且容错不得掩盖异常(解析失败 ≠ agent 意图)。
- **旧 runner 时序**:servicer fresh-start 分支会用新 GraphRunner 覆盖 `_active_runners[gid]` —— 从旧 runner 提取 compile_errors/失败任务摘要必须在覆盖之前完成;runner 是内存态,服务重启后不存在,磁盘兜底(扫描持久化目录)是提取失败时的唯一后备。

## Capabilities

### Modified Capabilities
- `function-implementation`: 用户反馈驱动的修正 —— 反馈时恢复工程现场(已生成文件/编译状态/失败任务),planner 基于现场重新规划(无关键字匹配);空 delta 容错防死路;executor 对话消息可见(模型生成,零模板);后端事件零口吻(纯数据,文案按归属渲染)

## Impact

- **后端 ai-service（Python）**:
  - `servicer.py` — fresh-start 时**在创建新 runner 覆盖 `_active_runners[gid]` 之前**从旧 runner 提取 compile_errors / 失败任务摘要注入新 state;提取失败(如服务重启后 runner 不存在)时仅依赖磁盘兜底,不得伪造历史
  - `graph.py` — Phase 3 入口从 `code_result` 反序列化恢复 `generated_files`,磁盘扫描兜底;feedback 场景空 delta 容错不报死路;删除 planner_reflect / 修复循环事件的后端拼接 `message`,事件只保留 decision/missing_files/errors 等数据字段
  - `nodes.py` — planner code_feedback prompt 注入现场;executor content 以 `agent_message` 事件发出(展示模型原文,无模板)
- **前端（ai-generation-app）**:AgentLog 新增 agent 消息气泡渲染;useCodeStream 处理 `agent_message` 事件;planner_reflect 状态卡按 decision 前端渲染(UI 文案归前端)
- **测试**:新增 feedback 现场恢复/空 delta 容错/agent 消息事件用例
