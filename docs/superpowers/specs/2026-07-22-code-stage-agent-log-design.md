# 功能开发节点 AgentLog + 三栏布局 — 设计方案

> 日期: 2026-07-22
> 状态: 设计完成
> 关联: [[2026-07-13-full-pipeline-workflow-design]]

## 1. 目标

功能开发节点重设计：左侧新增 AI 流式输出区（类似 Claude Code agent 模式），展示每步思考过程、工具调用、文件生成、编译状态。中间文件树，右侧代码查看器。预览 tab 实时编译渲染。

### 1.1 核心要求

1. 方案设计完成后点下一步 → 立即切换到功能开发节点
2. 工程文件 tab 三栏式：
   - 左 35%：AgentLog（思考 + 工具调用 + 文件生成 + 编译）
   - 中 20%：FileTree（文件目录树形结构）
   - 右 45%：CodeView（文件内容）
3. 预览 tab：文件开始写入即尝试编译，最大实时性
4. AI 输出完整展示每步：思考 → 工具调用 → 参数 → 结果
5. 编译错误可点击跳转到对应文件位置

## 2. 方案选型

选择**方案 B：AgentLog + useCodeStream composable**。

| 维度 | A: 事件驱动+AgentLog | B: AgentLog+useCodeStream (选中) |
|------|---------------------|-------------------------------|
| 关注点分离 | 中 | 高（composable 隔离 SSE 逻辑） |
| 组件复用 | 中 | 高（AgentLog 可复用于 review 等阶段） |
| 维护性 | 中 | 高 |
| 实现复杂度 | 中 | 中高 |

## 3. 布局设计

### 3.1 预览 Tab（保留现有）

复用 `PreviewFrame`，文件 chunk 到达时立即增量编译渲染。

### 3.2 工程文件 Tab（三栏）

```
┌─ TabBar: [工程文件] [实时预览] ────────────────────────┐
│                                                        │
│ ┌─ AgentLog ───┬─ FileTree ──┬─ CodeView ────────────┐│
│ │ 左 35%       │ 中 20%      │ 右 45%                ││
│ │ min-w 300px  │ min-w 160px │ flex-1               ││
│ │              │             │                       ││
│ │ 💭 思考过程   │ 📁 src/     │ ┌──────────────────┐ ││
│ │ ▾ 展开       │  ├ App.vue  │ │ <template>        │ ││
│ │   ...        │  ├ Header   │ │   <div>...</div>   │ ││
│ │              │  ├ Home     │ │ </template>       │ ││
│ │ 🔧 create_file│             │ └──────────────────┘ ││
│ │   ✅ App.vue │             │                       ││
│ │              │             │                       ││
│ │ 🔧 write_code│             │                       ││
│ │   📄 App.vue │             │                       ││
│ │   ...        │             │                       ││
│ │              │             │                       ││
│ │ ⚡ compile    │             │                       ││
│ │   ✅ 0 errors│             │                       ││
│ └──────────────┴─────────────┴───────────────────────┘│
└────────────────────────────────────────────────────────┘
```

### 3.3 交互

| 触发 | 效果 |
|------|------|
| 点击 AgentLog 工具卡片文件路径 | FileTree 选中 + CodeView 打开 |
| 点击编译错误条目 | 打开文件 + 定位错误行 |
| FileTree 点击文件 | CodeView 显示文件内容 |
| 编译事件卡片 | 绿色 ✅ / 红色 ❌ + 错误列表 |

## 4. SSE 事件协议

### 4.1 事件列表

| 事件 | 载荷 | 前端行为 |
|------|------|---------|
| `code_gen_start` | `{ files: [...] }` | 初始化 FileTree + AgentLog 汇总卡片 |
| `thinking_chunk` | `{ text: "..." }` | AgentLog 追加/新建思考气泡 |
| `tool_call` | `{ tool, args, status: "running" }` | AgentLog 新增 🔄 工具卡片 |
| `tool_result` | `{ tool, ok, detail }` | AgentLog 更新卡片 ✅/❌ |
| `file_start` | `{ path }` | AgentLog 📄 卡片 + FileTree 灰节点 |
| `file_chunk` | `{ path, content }` | 追加文件内容 + PreviewFrame 编译 |
| `file_complete` | `{ path }` | FileTree 节点实色 + AgentLog ✅ |
| `compile_status` | `{ ok, errors }` | AgentLog ⚡ 编译结果卡片 |
| `code_gen_done` | `{ total_files, compile_errors }` | 阶段完成 |

### 4.2 时序

```
code_gen_start → [tool_call → tool_result → file_start → file_chunk×N → file_complete → compile_status]×N → code_gen_done
```

其中 thinking_chunk 穿插在每轮 tool_call 前后。

## 5. 前端组件

### 5.1 新增组件

| 组件 | 职责 |
|------|------|
| `AgentLog.vue` | 流式事件渲染（思考/工具/文件/编译） |
| `useCodeStream.ts` | 代码阶段 SSE 事件消费 |

### 5.2 修改组件

| 组件 | 变更 |
|------|------|
| `CodeStagePanel.vue` | 工程文件 tab 改为三栏布局 |
| `stores/generation.ts` | 新增 `agentLogEntries` 状态 |
| `composables/useMultiAgent.ts` | dispatchGraphEvent 路由代码事件 |
| `types/generation.ts` | 新增 `AgentLogEntry` 类型 |

### 5.3 AgentLogEntry 类型

```typescript
interface AgentLogEntry {
  id: string
  type: 'thinking' | 'tool_call' | 'tool_result' | 'file_start'
       | 'file_complete' | 'compile' | 'phase_summary'
  timestamp: number
  // thinking
  thinkingText?: string
  thinkingDone?: boolean
  // tool
  toolName?: string
  toolArgs?: Record<string, any>
  toolStatus?: 'running' | 'done' | 'error'
  toolDetail?: string
  // file
  filePath?: string
  fileTotal?: number
  fileDone?: boolean
  // compile
  compileOk?: boolean
  compileErrors?: Array<{ file: string; line: number; message: string }>
  // summary
  summary?: string
}
```

### 5.4 AgentLog 消息卡片

```
💭 思考过程（流式累加，完成后折叠）

🔧 create_file  → App.vue         ✅ 已创建
🔧 write_code   → App.vue         📄 流式写入...
🔧 compile_project                 ⚡ ✅ 0 errors / ❌ 2 errors
   [点击错误跳转]
📄 App.vue 已完成 ✅
📊 生成完成：8 files，0 errors
```

## 6. 后端改造

### 6.1 graph.py Phase 3

```python
# 不再直接 await code_node(state)
# 改为 await code_node_streaming(state, event_queue)
# graph runner 并行读 queue + 等 task，直接转发事件
```

### 6.2 nodes.py code_node_streaming

```python
async def code_node_streaming(state, queue):
    # 每轮工具循环中：
    #   - on_thinking → queue.put(thinking_chunk)
    #   - tool 调用前 → queue.put(tool_call)
    #   - tool 返回后 → queue.put(tool_result)
    #   - write_code → queue.put(file_start/chunk/complete)
    #   - compile → queue.put(compile_status)
    # 完成后 → queue.put(code_gen_done)
    return updated_state
```

## 7. 实施要点

1. **FileTree** 复用 `FileExplorer` 内部的左侧面板，抽取为独立 `FileTree` 组件
2. **CodeView** 复用 `FileExplorer` 内部的右侧面板（FileTabBar + CodeEditor）
3. **AgentLog** 自动滚到底部，类似 ChatPanel
4. **PreviewFrame** 监听 `generatedFiles` 变化，每次 `file_chunk` 后尝试编译
5. 所有新增类型放入 `types/generation.ts`
