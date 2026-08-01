## Context

功能开发节点已完成 Planner+Executor ReAct 改造。Agent 按设计文档生成 Task DAG → Executor 逐 task 执行 → 完成后弹出"下一步"确认。问题是：用户只能确认通过，无法在发现产出缺失时介入纠偏。实际生成中常见"设计文档定义了 8 个组件但只生成了 6 个"的情况，用户需要告诉 Agent 问题所在并让它续写。

约束：输入框必须在 AgentLog 底部始终可见；停止按钮和发送通过 Enter 触发；反馈后 Planner 复用现有 ReAct 循环做自我审查，不另起炉灶。

## Goals / Non-Goals

**Goals:**
- AgentLog 底部新增固定反馈输入框 + 停止按钮，交互清晰（Enter 发送、Shift+Enter 换行、流式状态联动）
- 用户提交反馈后 Planner 对比设计文档与已生成文件，输出补充 Task DAG
- Executor 执行补充 task，AgentLog 实时展示（新增 task 分组、编译卡片）
- 反馈完成后卡片折叠为一行摘要，可展开查看历史
- 停止按钮取消当前 SSE 流，AgentLog 追加 ⏹ 标记

**Non-Goals:**
- 分析和设计节点的反馈输入（本次只做 code 节点）
- 跨节点反馈传递（只影响当前 code 阶段）
- 撤回/编辑已提交的反馈

## Decisions

### D1: 输入框嵌入 AgentLog 底部

在 AgentLog 的 scrollable 容器和固定 footer 之间分割。AgentLog 内部拆为 `flex flex-col h-full`：上方 `overflow-y-auto flex-1`（日志内容），下方固定 `border-t` footer（输入框 + 停止按钮）。

**替代方案**：输入框放在 CodeStagePanel 中 AgentLog 外部。否决原因：用户明确要求"AI 日志列表底部"。

### D2: Enter 发送，Shift+Enter 换行

`<textarea>` 监听 `keydown`：Enter 无 Shift → `preventDefault()` + 发送；Shift+Enter → 默认换行行为。发送按钮不显示，只用键盘。输入框 single-line 外观但支持多行（`rows="1"` + `max-height` 限制）。

### D3: 停止按钮 = 取消当前 SSE + 追加标记

停止按钮点击 → 调用 `canceller.abort()` 终止 fetch → AgentLog 追加 `type: 'cancel'` 卡片（⏹ 用户终止执行）→ 输入框立即可用。停止后 Planner 不受影响——下次用户发送反馈时，在现有文件基础上做自我审查。

**替代方案**：停止按钮终止整个生成。否决原因：只想停止当前流，保留已生成文件让用户审查。

### D4: 反馈后重新走 Planner+Executor 审查路径

```
用户 Enter 反馈
  → POST /api/v1/generation/feedback { generation_id, feedback }
  → gateway 转发 AI service
  → graph.py: 保存当前 generated_files，把 feedback 注入 state
  → Planner 收到特殊 prompt：
      "用户反馈：{feedback}。请对比设计文档与已生成文件，
       找出遗漏或差异，输出补充 Task DAG。如果没有遗漏，输出空 DAG。"
  → 如有补充 task → Executor 执行
  → SSE 事件沿用现有 task_start/file_chunk/compile 协议
  → 完成后前端折叠卡片
```

### D5: 反馈卡片折叠

每条反馈生成一个 `type: 'feedback_summary'` 的 AgentLogEntry，包含 `feedbackText`、`result`（补充文件数/错误数）、`expanded` 状态。默认折叠展示一行摘要，点击展开显示该反馈触发的完整 task 执行过程（嵌套在折叠区内）。

## Risks / Trade-offs

- **连续多次反馈导致 AgentLog 冗长** → 默认折叠历史反馈卡片，只有一行摘要
- **停止按钮误操作** → 停止只取消流，不丢失已生成文件；AgentLog 追加标记清晰可见
- **Planner 自我审查可能误判（说没有遗漏）** → 用户可再次提交反馈，强调具体要求
- **feedback 端点无认证** → 目前和 generate 端点一致，通过 generation_id 关联

## Open Questions

无。
