# AI Design Platform — Hybrid Backend Architecture Design

**Date:** 2026-06-23
**Status:** Approved
**Target Scale:** Medium-scale production (hundreds to thousands of concurrent users)

---

## 1. Overview

The AI Design Platform is a comprehensive AI application system combining:
- AI model inference & API proxying
- AI-assisted design generation
- AI Agent / workflow orchestration
- AI-driven frontend project generation

The backend adopts a **Python FastAPI + Go Gin hybrid architecture**, where each language handles what it does best.

---

## 2. Architecture Decision: Hybrid vs Monolith

### Rationale

| Factor | MVP Scale | Production Scale (our target) |
|--------|-----------|-------------------------------|
| Concurrent connections | Dozens | Hundreds to thousands (SSE long-lived) |
| Go goroutine memory advantage | Irrelevant | Critical — 10-20x less memory per connection |
| Independent scaling | Not needed | Required — AI services (GPU-bound, seconds latency) vs API gateway (stateless, milliseconds) |
| Fault isolation | Tolerable to crash together | Not acceptable — AI outage must not block user/project CRUD |
| Dual-language maintenance cost | Unacceptable drag on iteration | Justified by scale benefits |

### Decision: Go Gin (API Gateway + Business Logic) + Python FastAPI (AI Services)

```
Client → Go Gin (SSE/REST) → Python FastAPI (gRPC) → External AI APIs
                       ↕
              PostgreSQL / Redis
```

---

## 3. Project Structure

```
ai-design-platform-server/
├── proto/                          # gRPC contracts — single source of truth
│   ├── ai/v1/
│   │   ├── generation.proto        # Streaming generation service
│   │   ├── agent.proto             # Agent workflow service
│   │   └── embedding.proto         # Embedding service
│   └── common/v1/
│       └── types.proto             # Shared types
│
├── gateway/                        # Go Gin service
│   ├── cmd/server/main.go
│   ├── internal/
│   │   ├── handler/                # HTTP handlers
│   │   ├── service/                # Business logic
│   │   ├── middleware/             # Auth / rate limit / logging
│   │   ├── client/                 # gRPC clients (to Python)
│   │   └── model/                  # Domain models
│   ├── config/
│   └── Dockerfile
│
├── ai-service/                     # Python FastAPI + gRPC service
│   ├── app/
│   │   ├── main.py                 # FastAPI + gRPC server entry
│   │   ├── api/grpc/               # gRPC service implementations
│   │   ├── services/               # AI business logic
│   │   │   ├── llm/                # LLM provider abstraction
│   │   │   ├── agent/              # Agent execution engine
│   │   │   └── generation.py       # Generation management
│   │   └── core/                   # Config, DI
│   ├── pyproject.toml
│   └── Dockerfile
│
├── docker-compose.yml              # Local development
├── Makefile                        # Unified build/codegen
└── README.md
```

---

## 4. gRPC Proto Contracts

### Generation Service

```protobuf
service GenerationService {
  rpc StreamGenerate(GenerateRequest) returns (stream GenerateResponse);
  rpc CancelGeneration(CancelRequest) returns (CancelResponse);
}
```

- `StreamGenerate`: server-side streaming — Python calls LLM, returns tokens one by one
- `CancelGeneration`: cancels an in-progress generation (propagates from client SSE disconnect)

### Agent Service

```protobuf
service AgentService {
  rpc ExecuteAgent(AgentRequest) returns (AgentResponse);
  rpc WatchAgent(WatchRequest) returns (stream AgentEvent);
}
```

- `ExecuteAgent`: triggers async Agent workflow, returns run_id
- `WatchAgent`: server-side streaming for Agent execution progress

### Key Design Choices

- **gRPC over REST for interservice**: binary protocol, strong typing, 7-10x faster, bidirectional streaming support
- **Server-streaming for AI output**: matches the natural "push tokens as they arrive" pattern
- **Cancellation via gRPC context**: Go SSE disconnect → gRPC context cancel → Python stops LLM call

---

## 5. Go Gin Service (API Gateway)

### Responsibilities

- User authentication & authorization (JWT)
- Rate limiting & quota management
- Project / design / file CRUD
- SSE endpoint for streaming AI chat
- Bridges gRPC AI responses to SSE for frontend
- WebSocket management (if needed for real-time collaboration later)

### Route Design

```
POST   /api/v1/auth/login
POST   /api/v1/auth/refresh

GET    /api/v1/projects
POST   /api/v1/projects
GET    /api/v1/projects/:id

POST   /api/v1/chat/stream          # SSE: AI chat streaming
POST   /api/v1/chat/cancel/:id      # Cancel in-progress generation

POST   /api/v1/agents/execute       # Trigger agent workflow
GET    /api/v1/agents/runs/:id      # Agent run status

GET    /api/v1/generations/:id      # Generation history
POST   /api/v1/designs/generate     # AI design generation
POST   /api/v1/code/generate        # AI code generation
```

### Middleware Chain

```
Request → Recovery → Logging → Auth → RateLimit → Handler
```

### SSE Implementation (Why SSE, Not WebSocket)

| Feature | SSE | WebSocket |
|---------|-----|-----------|
| Direction | Unidirectional (server→client) | Bidirectional |
| AI streaming match | ✅ Natural fit | Overkill (no client push needed) |
| Browser API | `EventSource()` with auto-reconnect | Manual or 3rd-party |
| HTTP/2 multiplexing | ✅ Native | ❌ RFC prohibits |
| Proxy/LB compatibility | ✅ Standard HTTP | Requires Upgrade support |
| Cancel generation | Separate POST request | Close frame |

**Decision: SSE for AI streaming.** Client cancels via a separate POST endpoint, which is simpler and more explicit than abusing WebSocket close semantics.

### Core Handler Pattern

```go
func (h *ChatHandler) StreamChat(c *gin.Context) {
    // 1. Auth + quota check
    // 2. Set SSE headers
    c.Header("Content-Type", "text/event-stream")
    c.Header("Cache-Control", "no-cache")
    c.Header("X-Accel-Buffering", "no")

    // 3. Open gRPC stream to Python AI service
    grpcStream, _ := h.aiClient.StreamGenerate(ctx, &pbReq)

    // 4. Bridge gRPC → SSE
    c.Stream(func(w io.Writer) bool {
        resp, err := grpcStream.Recv()
        // ... map gRPC response types to SSE events
        c.SSEvent("token", payload.Token.Text)   // incremental token
        c.SSEvent("tool_call", tcJSON)           // tool use
        c.SSEvent("done", "[DONE]")              // completion
        return true
    })
}
```

---

## 6. Python FastAPI AI Service

### Responsibilities

- LLM provider abstraction (OpenAI, Anthropic, etc.)
- Prompt management and versioning
- AI Agent workflow orchestration (LangChain/LlamaIndex)
- RAG retrieval pipeline
- Embedding generation
- AI-driven code generation
- gRPC server for interservice communication

### Internal Structure

```
ai-service/app/
├── main.py                    # FastAPI + gRPC dual server
├── api/grpc/                  # gRPC service implementations
├── services/
│   ├── llm/provider.py        # LLM Provider interface
│   ├── llm/openai.py          # OpenAI adapter
│   ├── llm/anthropic.py       # Anthropic adapter
│   ├── agent/executor.py      # Agent execution engine
│   ├── agent/tools.py         # Agent tool registry
│   ├── generation.py          # Generation management
│   └── codegen.py             # Code generation
├── core/
│   ├── config.py              # Configuration
│   └── di.py                  # Dependency injection
```

### gRPC Server Implementation Pattern

```python
class GenerationServicer(GenerationServiceServicer):
    async def StreamGenerate(self, request, context):
        async for token in self.generation.stream(request):
            yield GenerateResponse(token=Token(text=token.text))
        yield GenerateResponse(complete=GenerationComplete(...))
```

---

## 7. Key Data Flows

### 7.1 Streaming AI Chat (Primary Flow)

```
Frontend                Go Gin                  Python AI           LLM API
  │                       │                       │                    │
  │ POST /chat/stream ───►│                       │                    │
  │ (opens SSE)           │ gRPC StreamGenerate ──►│                    │
  │                       │                       │ POST /v1/messages ─►
  │◄─ SSE: token "你" ───│◄── GenerateResponse ──│◄── delta "你" ────│
  │◄─ SSE: token "好" ───│◄── GenerateResponse ──│◄── delta "好" ────│
  │◄─ SSE: done ─────────│◄── GenerateResponse ──│◄── [complete] ────│
  │                       │                       │                    │
  │ (user cancels)        │                       │                    │
  │ POST /cancel/xxx ────►│                       │                    │
  │                       │ gRPC CancelGeneration ►│ context.cancel()   │
  │◄─ SSE: cancelled ────│◄── GenerateResponse ──│                    │
  │                       │                       │                    │
  │ (EventSource auto-reconnect, server resumes via Last-Event-ID)     │
```

### 7.2 Agent Workflow

```
Go Gin                    Python AI
  │                          │
  │ POST /agents/execute ───►│
  │◄── {run_id}              │
  │                          │ LangChain orchestrates:
  │                          │   think → tool_call → generate → verify
  │                          │
  │ GET /agents/runs/xxx ───►│
  │◄── {status, events}      │
```

---

## 8. Deployment Architecture

### Local Development

```yaml
docker-compose.yml:
  postgres:16
  redis:7-alpine
  go-gateway (port 8080)
  ai-service (port 50051)
```

### Production

```
Load Balancer (Nginx/Traefik)
    │
    ▼
Go Gin (3-5 replicas)  ← 水平扩展: CPU/连接数驱动
    │
    ▼ (gRPC)
Python AI (5-10 replicas)  ← 水平扩展: 请求队列深度驱动
    │
    ▼
PostgreSQL + Redis Cluster
```

### Independent Scaling Rationale

- **Go Gin**: scales with concurrent connections. Stateless, CPU-bound. HPA on CPU + connection count.
- **Python AI**: scales with pending AI tasks. IO-bound (waiting on LLM APIs). HPA on request queue depth.
- The two services have fundamentally different resource profiles — this is the primary reason for separation.

---

## 9. Fault Isolation

| Scenario | Go Gin Behavior | Python AI Behavior |
|----------|----------------|-------------------|
| Python AI down | Returns 503 for AI endpoints; user/profile CRUD continues | N/A |
| Go Gin down | N/A | Not directly affected (no client-facing role) |
| Go restarts | Reconnects gRPC; replays queued Redis messages | Holds in-progress generations briefly |
| Python restarts | Queues new AI requests; returns "AI busy" for 2-5s | In-progress generations lost (acceptable) |

---

## 10. Cross-Cutting Concerns

### Authentication
- JWT issued by Go, validated at Go middleware layer
- gRPC calls carry user_id in metadata (not tokens — Python trusts the gateway on internal network)

### Observability
- OpenTelemetry for distributed tracing (Go ↔ Python correlation)
- Structured logging (Go: zap, Python: structlog)
- gRPC metrics (latency, error rate, active streams)

### Code Generation
- `make proto` — generates Go and Python code from `proto/`
- Proto files are the single source of truth for interservice contracts
- CI enforces proto changes trigger integration tests

---

## 11. Future Considerations (Out of Scope for Phase 1)

- **Message Queue for async AI jobs**: Kafka/RabbitMQ for long-running Agent workflows
- **WebSocket for real-time collaboration**: If multi-user live collaboration is added
- **Python model serving**: If local model inference (not just API proxying) is needed
- **Multi-tenancy**: Tenant isolation at Go middleware + DB level
