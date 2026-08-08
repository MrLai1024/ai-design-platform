## Context

功能开发节点的用户反馈链路当前是断的:用户在工程文件下方输入框输入"继续"、"需要修改 xx 文件"后,前端 `confirmStage` 走 fresh-start,ai-service servicer 重建**全新 state** —— `generated_files = {}`、旧 Task DAG/失败任务/`compile_errors` 全部丢失。planner 的 `code_feedback` 分支只看到"设计方案 + 反馈文本",凭猜修正;输入"继续"时可能重跑全部任务,或空 delta 触发 `"Planner produced no tasks"` 死路。同时 executor 每轮的正式回复(`content`)只用来检测 `__TASK_DONE__`,从未发给前端,AgentLog 无对话感。

约束(来自 proposal 设计原则):
- **零硬编码行为** —— 反馈处理不匹配任何关键字,所有输入同一路径
- **零模板文案** —— agent 对话文本 100% 模型输出
- **后端事件零口吻** —— 后端事件只带结构化数据,文案按归属渲染(对话气泡=模型原文,状态卡=前端 UI 模板)
- **鲁棒性 ≠ 语义** —— 空 delta 容错是防御性处理,且不得掩盖解析失败

## Goals / Non-Goals

**Goals:**
- 反馈 fresh-start 时恢复工程现场:已生成文件清单、上次编译错误、失败任务摘要
- planner 基于现场输出 delta 任务,不做关键字匹配
- feedback 场景下 agent 明确输出空 delta → 正常收尾(防死路),解析失败仍报错
- executor `content` 以 `agent_message` 事件流式展示为对话气泡
- 后端事件去掉拼接文案,planner_reflect 等状态卡由前端按 decision 渲染

**Non-Goals:**
- 不做方向 B(servicer 保留旧 state 走 resume/带历史重规划) —— 保持 fresh-start 语义
- 不做 planner 决策卡的中文映射表替换 —— 前端渲染即可
- 不改 7.16 修复循环的执行逻辑,只去掉其事件里的后端文案

## Decisions

### D1: 现场恢复的数据源优先级

`generated_files` 恢复来源,按可靠性排序:

1. **`code_result` 反序列化** — graph.py 结尾把 `generated_files` 序列化进 `state["code_result"]`,prefill 已带回,是最完整可靠的事实源。在 graph.py Phase 3 入口(`if not state.get("generated_files")` 分支内)反序列化恢复。
2. **磁盘扫描兜底** — `code_result` 缺失/损坏时,`os.walk` 扫描 `data/generated/<gid>/`,排除点目录(`.ai-memory` 等),限制文件数(如 ≤500)防大目录拖垮。

`compile_errors` / 失败任务摘要来源:**旧 runner**。servicer fresh-start 分支在**创建新 runner 覆盖 `_active_runners[gid]` 之前**,从 `existing_runner._state` 提取:
- `compile_errors`(最终编译错误列表)
- `planner_dag.tasks` 中 `status == "failed"` 的:id、description、failure_kind、missing_paths

提取失败(重启后 runner 不存在)时不伪造历史 —— 只依赖磁盘兜底的文件,planner 的修复循环会重新编译获得最新状态。

**备选**:servicer 按 gid 持久化 state 到磁盘。放弃 —— 改动面大,且 runner 内存态在单次会话内已足够;重启后磁盘文件清单已能支撑反馈。

### D2: planner 现场注入(上下文数据,非事件文案)

`planner_node` 的 code_feedback 分支改为注入三块**结构化事实**(拼接进 prompt 是上下文数据,允许;与"事件零口吻"不冲突 —— 那是展示文案约束):

```
## 项目现场(已生成文件,只读,不得重建/覆盖)
- src/main.ts (1.2 KB)
- ...

## 上次最终编译状态
[TS2322] src/App.vue:5 — Type 'string' is not assignable to 'number'

## 失败任务(执行记录)
- task-2 (生成 App.vue): failure=missing_file, 缺: src/views/home-view.vue
```

已生成文件清单来自恢复后的 `state["generated_files"]`(大小从磁盘计算);compile_errors 与失败任务来自 D1 注入的 state 字段(新字段 `state["feedback_history"]`,结构化为 dict 而非字符串)。反馈文本原样附在 prompt 末尾 —— **不解析、不匹配、不分类**,planner 自主判断。

### D3: 空 delta 容错的位置与条件

graph.py 的 `if not tasks:` 分支(首次规划)保持报错;在 **incremental replan 路径**(Step 3.6)与 code_feedback 分支共用判断:

- `extract_task_dag` **解析成功且 tasks 为空** 且 **code_feedback 非空** → 容错:emit planner_reflect(decision=no_changes)+ 进入最终编译收尾流程(修复循环照常仲裁)
- 解析失败(异常兜底 `{"tasks": []}`)→ **照常报错**,不静默收尾

实现:replan 路径的解析失败目前静默兜底为空后继续 —— 需在 `except` 分支记录失败标记,容错判断时区分。首次规划路径(planner_node 输出)同样适用:code_feedback 非空 + 解析成功空列表 → 容错。

### D4: agent_message 事件与后端零口吻

- executor_task 每轮 `response["content"]` 非空且非纯 `__TASK_DONE__` 时,emit `agent_message` 事件(`{"text": content}`)。前端 AgentLog 渲染为对话气泡(新条目类型,与 thinking/tool_call 视觉区分)。
- 删除后端拼接文案:graph.py 中 planner_reflect 事件(`replan_missing_files` / `final_compile_*`)的 `message` 字段、7.16 修复循环事件的 `message` —— 事件只留 `decision`/`missing_files`/`failed_task_ids`/`errors` 等数据。`planner_dag` 事件的 `reasoning` 是模型输出,保留。
- 前端 `useCodeStream` 的 planner_reflect 分支改为按 `decision` 渲染短状态文本(如 `replan_missing_files` → "增量重规划:缺 N 个文件";`final_compile_repair` → "最终编译修复";未知 decision 显示 key 本身)。

### D5: 交互感的来源(全部模型输出)

- executor content → agent_message 气泡(agent 的"话")
- planner 的 reasoning 已有(thinking_chunk / plannerReasoning),反馈场景下 planner 的 reasoning 就是对反馈的完整回应,保持原样展示
- 不新增任何后端生成的回执/文案

## Risks / Trade-offs

- **[code_result 与磁盘不一致]** → 磁盘兜底时以磁盘为事实源;两者共存时 code_result 优先(它是最近一次序列化)。
- **[旧 runner 状态过期]** —— 用户可能多次反馈,runner 每次被覆盖,提取的是最近一次生成的状态 → 可接受:反馈总是针对最近一次生成结果。
- **[空 delta 容错掩盖 planner 退化]** —— 只对"解析成功的空列表"容错,解析失败照常报错 → 有兜底。
- **[agent_message 噪音]** —— executor 的 content 可能夹带 `__TASK_DONE__` 标记 → 展示时去除标记,空白 content 不发事件。
- **[磁盘扫描性能]** —— 文件数上限 + 跳过点目录 → 有界。

## Migration Plan

1. 后端:servicer 提取注入 → graph.py 恢复/容错 → nodes.py prompt 注入 + agent_message 事件 → 删事件 message
2. 前端:AgentLog 气泡 + useCodeStream decision 渲染
3. 测试覆盖后全量回归(后端 pytest / node-compiler / 前端 vitest)

回滚:事件 message 删除是展示层变更,回滚只需恢复字段;现场恢复是增量逻辑,不影响无反馈路径。

## Open Questions

无。设计依赖均已通过代码走查确认(servicer fresh-start 覆盖时序、graph.py Phase 3 入口、executor content 流向、useCodeStream planner_reflect 渲染)。
