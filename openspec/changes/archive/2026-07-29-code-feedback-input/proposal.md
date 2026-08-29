## Why

功能开发节点缺少用户纠偏机制。当前 Agent 生成完代码后只有二元的"下一步"确认——用户无法在发现遗漏时让 Agent 自我审查并续写。实际使用中，生成产出与设计文档之间常有差距（缺文件、接口不匹配、组件遗漏），需要一个输入框让用户描述问题，Agent 对比设计文档后开启新一轮 ReAct 循环补全。

## What Changes

- **AgentLog 底部固定反馈输入框**：始终可见，Enter 键发送（Shift+Enter 换行），生成中发送按钮灰色不可点，空闲时可用
- **停止执行按钮**：与输入框同一行右侧，流式生成中红色可用，一键取消当前 SSE 流，AgentLog 追加 ⏹ 卡片，输入框立即可用
- **Planner 自我审查 + 续写闭环**：用户反馈通过新端点传入后端，Planner 对比设计文档与已生成文件找差异，输出补充 Task DAG，Executor 继续执行补充 task，完成后反馈卡片折叠为一行摘要（点击可展开）
- **后端反馈端点**：`POST /api/v1/generation/feedback` 接收 `{ generation_id, feedback }`，注入 Planner ReAct 循环触发自我审查

## Capabilities

### New Capabilities

- `code-feedback-input`: AgentLog 底部反馈输入框 + 停止按钮 UI，Enter 发送 / Shift+Enter 换行，流式状态联动
- `code-feedback-loop`: 后端反馈接收 → Planner 自我审查（对比设计文档 → 补充 Task DAG）→ Executor 续写 → 反馈卡片折叠

### Modified Capabilities

（无现有 spec）

## Impact

- **前端**（`ai-generation-app`）：`AgentLog.vue` 底部新增输入框 + 停止按钮；`useMultiAgent.ts` 新增 `sendFeedback()`、`cancelGeneration()` 方法；`generation.ts` store 新增 `codeFeedback`、`isCancelling` 状态
- **后端**（`ai-service`）：`graph.py` 新增 `handle_code_feedback()` 方法复用 Planner+Executor 自我审查；`servicer.py` 新增 feedback 处理；`nodes.py` Planner prompt 增加 self-review 指令
- **网关**（gateway）：新增 `POST /api/v1/generation/feedback` 端点转发
