## 1. AgentLog 底部输入框 + 停止按钮

- [x] 1.1 AgentLog 模板拆分：上方滚动区 + 下方固定 footer
- [x] 1.2 新增 cancel / feedback_summary 卡片类型 + 渲染
- [x] 1.3 输入框 Enter 发送 / Shift+Enter 换行键盘交互
- [x] 1.4 停止按钮：流式中红色可用，空闲时灰色 disabled
- [x] 1.5 输入框发送状态联动（isStreaming 控制）
- [x] 1.6 反馈卡片折叠交互：默认一行摘要，点击展开

## 2. 前端反馈发送与流取消

- [x] 2.1 useMultiAgent.ts 新增 sendFeedback()
- [x] 2.2 useMultiAgent.ts 新增 cancelGeneration() (AbortController)
- [x] 2.3 store 新增 setStreaming；confirmStage 使用 AbortController

## 3. 后端反馈端点与 Planner 自我审查

- [x] 3.1 proto 跳过（复用现有 metadata 注入）
- [x] 3.2 gateway 新增 POST /api/v1/generation/feedback + 内存 store
- [x] 3.3 servicer 读取 code_feedback metadata 写入 state
- [x] 3.4 nodes.py planner_node 检测 code_feedback → 自我审查模式
- [x] 3.5 graph.py 复用现有 Planner+Executor 流
- [x] 3.6 AgentLog 反馈卡片已在 1.2 前端实现
