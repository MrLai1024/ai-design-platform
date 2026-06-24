# HTTP API 接口文档

Go Gin API Gateway — `http://localhost:8080`

---

## 1. 健康检查

### GET /health

存活探针（Liveness Probe），用于 K8s / Docker 健康检查。

**请求：**
```
GET /health
```

**响应 `200 OK`：**
```json
{
  "status": "ok"
}
```

---

### GET /ready

就绪探针（Readiness Probe），检查服务及其依赖是否就绪。Phase 2 将增加 gRPC / DB / Redis 连通性检测。

**请求：**
```
GET /ready
```

**响应 `200 OK`：**
```json
{
  "status": "ready"
}
```

---

## 2. AI 对话（流式）

### POST /api/v1/chat/stream

向 AI 发送对话请求，通过 **SSE (Server-Sent Events)** 流式返回生成结果。

**请求：**
```
POST /api/v1/chat/stream
Content-Type: application/json
```

**请求体：**
```json
{
  "model": "claude-sonnet-4-6",
  "messages": [
    {
      "role": "system",
      "content": "你是一个 AI 设计助手"
    },
    {
      "role": "user",
      "content": "帮我设计一个登录页面"
    }
  ]
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `model` | `string` | ✅ | 模型名称，如 `claude-sonnet-4-6`、`claude-opus-4-8`、`mock-model` |
| `messages` | `array` | ✅ | 对话消息列表 |
| `messages[].role` | `string` | ✅ | 角色：`system`、`user`、`assistant` |
| `messages[].content` | `string` | ✅ | 消息内容 |

**响应 `200 OK`（SSE 流）：**
```
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
```

SSE 事件类型：

| 事件 | 说明 | 负载 |
|------|------|------|
| `meta` | 流的元信息（最先发送） | `{"generation_id": "uuid"}` |
| `token` | 增量文本 token | `{"index": 0, "text": "你好"}` |
| `tool_call` | AI 请求调用工具 | `{"id": "...", "name": "read_file", "arguments": "..."}` |
| `complete` | 生成正常结束 | `{"finish_reason": "stop"}` |
| `error` | 生成出错 | `{"code": "INTERNAL", "message": "..."}` |
| `done` | 流结束标记 | `[DONE]` |

**流式输出示例：**
```
event: meta
data: {"generation_id":"550e8400-e29b-41d4-a716-446655440000"}

event: token
data: {"index":0,"text":"好的"}

event: token
data: {"index":1,"text":"，我来"}

event: token
data: {"index":2,"text":"设计一个"}

event: token
data: {"index":3,"text":"登录页面"}

event: complete
data: {"finish_reason":"stop"}

event: done
data: [DONE]
```

**错误响应 `503 Service Unavailable`：**
```json
{
  "error": "AI service unavailable"
}
```

**错误响应 `400 Bad Request`：**
```json
{
  "error": "Key: 'ChatRequest.Model' Error:Field validation for 'Model' failed on the 'required' tag"
}
```

---

### POST /api/v1/chat/cancel/:id

取消正在进行的 AI 生成。

**请求：**
```
POST /api/v1/chat/cancel/550e8400-e29b-41d4-a716-446655440000
```

**路径参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| `id` | `string` | `generation_id`，从 SSE `meta` 事件获取 |

**响应 `200 OK`：**
```json
{
  "generation_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "cancelled"
}
```

**错误响应 `400 Bad Request`：**
```json
{
  "error": "generation_id is required"
}
```

---

## 3. 客户端集成示例

### JavaScript (EventSource)

```javascript
const eventSource = new EventSource('/api/v1/chat/stream', {
  // Note: EventSource 不支持 POST，实际使用 fetch + ReadableStream
});

// 推荐用 fetch 实现带 POST 的 SSE：
async function streamChat(model, messages) {
  const response = await fetch('http://localhost:8080/api/v1/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model, messages }),
  });

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';

    for (const line of lines) {
      if (line.startsWith('event:')) {
        const eventType = line.slice(6).trim();
        // 下一行是 data:
        continue;
      }
      if (line.startsWith('data:')) {
        const data = JSON.parse(line.slice(5).trim());
        console.log(eventType, data);
        // 更新 UI
      }
    }
  }
}

// 取消生成
async function cancelChat(generationId) {
  await fetch(`/api/v1/chat/cancel/${generationId}`, { method: 'POST' });
}
```

### curl (命令行测试)

```bash
# 流式对话
curl -N -X POST http://localhost:8080/api/v1/chat/stream \
  -H "Content-Type: application/json" \
  -d '{
    "model": "mock-model",
    "messages": [
      {"role": "user", "content": "你好"}
    ]
  }'

# 取消生成
curl -X POST http://localhost:8080/api/v1/chat/cancel/<generation_id>
```

---

## 3. 会话管理 API

### POST /api/v1/conversations

创建新会话。

**请求：**
```json
{
  "title": "我的设计讨论"
}
```

**响应 `201 Created`：**
```json
{
  "id": "uuid",
  "title": "我的设计讨论",
  "created_at": "2026-06-24T23:49:07Z"
}
```

---

### GET /api/v1/conversations

获取所有会话列表（按最近更新排序）。

**响应 `200 OK`：**
```json
{
  "conversations": [
    {
      "id": "uuid",
      "title": "我的设计讨论",
      "msg_count": 4,
      "created_at": "...",
      "updated_at": "..."
    }
  ]
}
```

---

### GET /api/v1/conversations/:id

获取单个会话详情（含全部消息）。

**响应 `200 OK`：**
```json
{
  "id": "uuid",
  "title": "我的设计讨论",
  "messages": [
    {"id": "msg-1", "role": "user", "content": "帮我设计一个登录页面", "created_at": "..."},
    {"id": "msg-2", "role": "assistant", "content": "好的，我来设计...", "created_at": "..."}
  ],
  "created_at": "...",
  "updated_at": "..."
}
```

**响应 `404 Not Found`：**
```json
{ "error": "conversation not found" }
```

---

### POST /api/v1/conversations/:id/messages

向会话发送消息，通过 **SSE** 流式返回 AI 回复。自动将完整对话历史发送给 AI。

**请求：**
```json
{
  "model": "glm-5.2",
  "content": "把这个改成深色主题"
}
```

**SSE 事件（与 /chat/stream 相同 + 额外字段）：**
```
event: meta
data: {"conversation_id": "...", "generation_id": "...", "message_id": "..."}

event: token
data: {"text": "好的", "index": 0}

event: complete
data: {"finish_reason": "stop"}

event: done
data: [DONE]
```

AI 回复会在生成完成后自动保存到会话中。

---

### DELETE /api/v1/conversations/:id

删除会话。

**响应 `200 OK`：**
```json
{ "status": "deleted" }
```

---

### curl 示例：完整对话流程

```bash
# 1. 创建会话
CONV=$(curl -s -X POST http://localhost:8080/api/v1/conversations \
  -H "Content-Type: application/json" \
  -d '{"title":"设计讨论"}' | python -c "import sys,json; print(json.load(sys.stdin)['id'])")

# 2. 流式发送消息
curl -N -X POST "http://localhost:8080/api/v1/conversations/$CONV/messages" \
  -H "Content-Type: application/json" \
  -d '{"model":"mock-model","content":"你好，帮我设计一个登录页面"}'

# 3. 继续对话（自动携带历史）
curl -N -X POST "http://localhost:8080/api/v1/conversations/$CONV/messages" \
  -H "Content-Type: application/json" \
  -d '{"model":"mock-model","content":"改成深色主题"}'

# 4. 查看对话历史
curl -s "http://localhost:8080/api/v1/conversations/$CONV"
```
