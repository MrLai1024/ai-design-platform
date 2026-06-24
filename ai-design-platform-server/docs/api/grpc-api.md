# gRPC API 接口文档

Python AI Service — `ai-service:50051`（内部服务，不直接暴露前端）

协议文件：`proto/ai/v1/generation.proto`、`proto/ai/v1/agent.proto`

---

## 1. GenerationService — AI 生成服务

### StreamGenerate（服务端流式）

调用 LLM 进行文本/代码生成，以服务端流式返回 token。

```
rpc StreamGenerate(GenerateRequest) returns (stream GenerateResponse);
```

**请求 `GenerateRequest`：**

```json
{
  "generation_id": "550e8400-e29b-41d4-a716-446655440000",
  "model": "claude-sonnet-4-6",
  "messages": [
    {"role": "system", "content": "你是一个设计助手"},
    {"role": "user", "content": "帮我设计一个登录页面"}
  ],
  "config": {
    "temperature": 0.7,
    "max_tokens": 4096,
    "top_p": 1.0,
    "stop_sequences": []
  },
  "metadata": {
    "user_id": "user-123",
    "trace_id": "trace-abc"
  }
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `generation_id` | `string` | ✅ | 幂等键，用于取消和去重 |
| `model` | `string` | ✅ | 模型名（`claude-sonnet-4-6`、`gpt-4o` 等） |
| `messages` | `Message[]` | ✅ | 对话消息 |
| `config.temperature` | `double` | ❌ | 采样温度（默认 0.7） |
| `config.max_tokens` | `int32` | ❌ | 最大生成 token 数（默认 4096） |
| `config.top_p` | `double` | ❌ | 核采样 |
| `config.stop_sequences` | `string[]` | ❌ | 停止序列 |
| `metadata` | `map<string,string>` | ❌ | 追踪元数据 |

**Message：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `role` | `string` | `system`、`user`、`assistant` |
| `content` | `string` | 消息内容 |

**流式响应 `GenerateResponse`（oneof payload）：**

| 变体 | 字段 | 说明 |
|------|------|------|
| `token` | `Token { text, index }` | 增量 token |
| `tool_call` | `ToolCall { id, name, arguments }` | AI 请求工具调用 |
| `complete` | `GenerationComplete { finish_reason, usage }` | 生成完成 |
| `error` | `GenerationError { code, message }` | 错误 |

**GenerationComplete.finish_reason：**

| 值 | 说明 |
|------|------|
| `stop` | 自然结束 |
| `length` | 达到 max_tokens 限制 |
| `cancelled` | 被取消 |

---

### CancelGeneration（一元调用）

取消正在进行的生成。

```
rpc CancelGeneration(CancelRequest) returns (CancelResponse);
```

**请求 `CancelRequest`：**
```json
{
  "generation_id": "550e8400-e29b-41d4-a716-446655440000",
  "reason": "user_cancelled"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `generation_id` | `string` | 要取消的生成 ID |
| `reason` | `string` | 取消原因 |

**响应 `CancelResponse`：**
```json
{
  "success": true
}
```

**取消传播链路：**
```
Client SSE 断开 / POST /cancel
    → Go Gin context cancel
        → gRPC StreamGenerate context cancel
            → Python servicer 检测 context.cancelled()
                → LLM API 调用中止
```

---

## 2. AgentService — Agent 工作流服务

### ExecuteAgent（一元调用）

触发异步 Agent 工作流，返回 `agent_run_id` 用于后续查询。

```
rpc ExecuteAgent(AgentRequest) returns (AgentResponse);
```

**请求 `AgentRequest`：**
```json
{
  "agent_id": "design-agent",
  "workflow_type": "design",
  "input": "{\"requirement\": \"设计一个电商首页\", \"style\": \"modern\"}",
  "metadata": {
    "user_id": "user-123"
  }
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `agent_id` | `string` | ✅ | Agent 标识 |
| `workflow_type` | `string` | ✅ | 工作流类型：`design`、`codegen`、`analysis` |
| `input` | `string` | ✅ | JSON 编码的输入参数 |
| `metadata` | `map<string,string>` | ❌ | 追踪元数据 |

**响应 `AgentResponse`：**
```json
{
  "agent_run_id": "run-xxx-xxx",
  "status": "queued"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `agent_run_id` | `string` | 运行 ID，用于 WatchAgent |
| `status` | `string` | `queued`、`running` |

---

### WatchAgent（服务端流式）

订阅 Agent 执行进度，实时推送状态变更。

```
rpc WatchAgent(WatchRequest) returns (stream AgentEvent);
```

**请求 `WatchRequest`：**
```json
{
  "agent_run_id": "run-xxx-xxx"
}
```

**流式响应 `AgentEvent`：**
```json
{
  "agent_run_id": "run-xxx-xxx",
  "status": "GENERATING",
  "message": "正在生成前端代码...",
  "data": "{\"files_generated\": 3}"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `agent_run_id` | `string` | 运行 ID |
| `status` | `string` | `THINKING`、`TOOL_CALLING`、`GENERATING`、`DONE`、`ERROR` |
| `message` | `string` | 人类可读的状态描述 |
| `data` | `string` | JSON 编码的中间数据 |

---

## 3. Proto 文件位置

```
proto/
├── buf.yaml                    # Buf 配置（lint + breaking change）
├── buf.gen.yaml                # 代码生成配置（Go + Python）
└── ai/v1/
    ├── generation.proto        # GenerationService 定义
    └── agent.proto             # AgentService 定义
```

**生成客户端代码：**
```bash
make proto-gen    # buf generate proto
```
