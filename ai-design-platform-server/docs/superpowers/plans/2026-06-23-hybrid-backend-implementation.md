# Hybrid Backend — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the AI Design Platform backend with Go Gin API gateway (SSE/REST) + Python FastAPI AI service (gRPC), delivering end-to-end streaming AI chat.

**Architecture:** Go Gin handles auth, routing, SSE streaming to frontend. Python FastAPI exposes gRPC server for AI generation/agent services. Services communicate via gRPC with proto files as single source of truth. SSE chosen over WebSocket for unidirectional AI token streaming.

**Tech Stack:** Go 1.22 + Gin + gRPC-Go | Python 3.12 + FastAPI + gRPC-Python + LangChain | PostgreSQL + Redis | Docker Compose

---

## File Structure Map

```
ai-design-platform-server/
├── proto/                              # Create all
│   ├── buf.gen.yaml                    # buf codegen config
│   ├── buf.yaml                        # buf lint config
│   └── ai/v1/
│       ├── generation.proto
│       └── agent.proto
│
├── gen/                                # Generated code (gitignored)
│   ├── go/                             # Go protobuf + gRPC stubs
│   └── python/                         # Python protobuf + gRPC stubs
│
├── gateway/                            # Go Gin service
│   ├── go.mod
│   ├── go.sum
│   ├── cmd/server/main.go
│   ├── internal/
│   │   ├── config/config.go
│   │   ├── middleware/
│   │   │   ├── logging.go
│   │   │   └── auth.go
│   │   ├── handler/
│   │   │   ├── health.go
│   │   │   └── chat.go
│   │   └── client/
│   │       └── ai.go                   # gRPC client to Python
│   └── Dockerfile
│
├── ai-service/                         # Python AI service
│   ├── pyproject.toml
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                     # gRPC server entry
│   │   └── services/
│   │       ├── __init__.py
│   │       ├── llm/
│   │       │   ├── __init__.py
│   │       │   ├── provider.py         # Abstract LLM provider
│   │       │   ├── mock.py             # Mock provider for dev/testing
│   │       │   └── anthropic.py        # Anthropic adapter
│   │       └── generation/
│   │           ├── __init__.py
│   │           └── servicer.py         # gRPC GenerationService impl
│   └── Dockerfile
│
├── docker-compose.yml
├── Makefile
├── .gitignore
└── README.md
```

---

### Task 1: Project Scaffolding & Root Configuration

**Files:**
- Create: `ai-design-platform-server/.gitignore`
- Create: `ai-design-platform-server/Makefile`
- Create: `ai-design-platform-server/README.md`

- [ ] **Step 1: Create .gitignore**

```gitignore
# Generated code
gen/

# Go
gateway/cmd/server/server
*.exe

# Python
__pycache__/
*.pyc
.venv/
*.egg-info/

# IDE
.idea/
.vscode/
*.swp

# Environment
.env
.env.local

# Docker
.docker/
```

- [ ] **Step 2: Create root Makefile**

```makefile
.PHONY: proto-gen proto-clean dev-up dev-down build test

# Proto code generation
proto-gen:
	buf generate proto

proto-clean:
	rm -rf gen/

# Docker Compose
dev-up:
	docker compose up --build -d

dev-down:
	docker compose down

dev-logs:
	docker compose logs -f

# Build
build: build-gateway build-ai

build-gateway:
	cd gateway && go build -o cmd/server/server ./cmd/server

build-ai:
	cd ai-service && pip install -e .

# Test
test: test-gateway test-ai

test-gateway:
	cd gateway && go test ./...

test-ai:
	cd ai-service && pytest
```

- [ ] **Step 3: Create README.md**

```markdown
# AI Design Platform — Server

Hybrid backend: Go Gin (API Gateway) + Python FastAPI (AI Services)

## Quick Start

```bash
make dev-up       # Start all services
make dev-down     # Stop
make dev-logs     # View logs
```

## Architecture

- **gateway/** — Go Gin HTTP/SSE server (port 8080)
- **ai-service/** — Python gRPC AI server (port 50051)
- **proto/** — Shared gRPC contract definitions

## Prerequisites

- Go 1.22+
- Python 3.12+
- Docker & Docker Compose
- buf (protobuf toolchain): `brew install buf` or see https://buf.build
```

---

### Task 2: Proto Contract Definitions

**Files:**
- Create: `proto/buf.yaml`
- Create: `proto/buf.gen.yaml`
- Create: `proto/ai/v1/generation.proto`
- Create: `proto/ai/v1/agent.proto`

- [ ] **Step 1: Create buf.yaml (lint/breaking change config)**

```yaml
version: v2
modules:
  - path: .
lint:
  use:
    - DEFAULT
breaking:
  use:
    - FILE
```

- [ ] **Step 2: Create buf.gen.yaml (code generation config)**

```yaml
version: v2
plugins:
  # Go stubs
  - remote: buf.build/protocolbuffers/go
    out: ../gen/go
    opt:
      - paths=source_relative
  - remote: buf.build/grpc/go
    out: ../gen/go
    opt:
      - paths=source_relative
  # Python stubs
  - remote: buf.build/protocolbuffers/python
    out: ../gen/python
  - remote: buf.build/grpc/python
    out: ../gen/python
```

- [ ] **Step 3: Create proto/ai/v1/generation.proto**

```protobuf
syntax = "proto3";

package ai.v1;

option go_package = "ai-design-platform/gen/go/ai/v1;aiv1";

// GenerationService handles AI text/code generation with streaming.
service GenerationService {
  // StreamGenerate performs LLM generation, returning tokens as they arrive.
  rpc StreamGenerate(GenerateRequest) returns (stream GenerateResponse);

  // CancelGeneration stops an in-progress generation.
  rpc CancelGeneration(CancelRequest) returns (CancelResponse);
}

message GenerateRequest {
  string generation_id = 1;
  string model = 2;
  repeated Message messages = 3;
  GenerationConfig config = 4;
  map<string, string> metadata = 5;
}

message Message {
  string role = 1;     // "system" | "user" | "assistant"
  string content = 2;
}

message GenerationConfig {
  double temperature = 1;
  int32 max_tokens = 2;
  double top_p = 3;
  repeated string stop_sequences = 4;
}

message GenerateResponse {
  oneof payload {
    Token token = 1;
    ToolCall tool_call = 2;
    GenerationComplete complete = 3;
    GenerationError error = 4;
  }
}

message Token {
  string text = 1;
  int32 index = 2;
}

message ToolCall {
  string id = 1;
  string name = 2;
  string arguments = 3;  // JSON string
}

message GenerationComplete {
  string finish_reason = 1;  // "stop" | "length" | "cancelled"
  Usage usage = 2;
}

message Usage {
  int32 prompt_tokens = 1;
  int32 completion_tokens = 2;
  int32 total_tokens = 3;
}

message GenerationError {
  string code = 1;
  string message = 2;
}

message CancelRequest {
  string generation_id = 1;
  string reason = 2;
}

message CancelResponse {
  bool success = 1;
}
```

- [ ] **Step 4: Create proto/ai/v1/agent.proto**

```protobuf
syntax = "proto3";

package ai.v1;

option go_package = "ai-design-platform/gen/go/ai/v1;aiv1";

// AgentService handles AI agent workflow execution.
service AgentService {
  // ExecuteAgent triggers an async agent workflow, returning a run_id.
  rpc ExecuteAgent(AgentRequest) returns (AgentResponse);

  // WatchAgent streams agent execution progress.
  rpc WatchAgent(WatchRequest) returns (stream AgentEvent);
}

message AgentRequest {
  string agent_id = 1;
  string workflow_type = 2;  // "design" | "codegen" | "analysis"
  string input = 3;          // JSON-encoded input parameters
  map<string, string> metadata = 5;
}

message AgentResponse {
  string agent_run_id = 1;
  string status = 2;  // "queued" | "running"
}

message WatchRequest {
  string agent_run_id = 1;
}

message AgentEvent {
  string agent_run_id = 1;
  string status = 2;   // "THINKING" | "TOOL_CALLING" | "GENERATING" | "DONE" | "ERROR"
  string message = 3;  // Human-readable status description
  string data = 4;     // JSON-encoded intermediate data
}
```

---

### Task 3: Proto Code Generation

- [ ] **Step 1: Install buf (if not already)**

Run: `buf --version`
If missing: `curl -sSL https://github.com/bufbuild/buf/releases/latest/download/buf-Linux-x86_64 -o /usr/local/bin/buf && chmod +x /usr/local/bin/buf`

- [ ] **Step 2: Generate proto stubs**

```bash
cd proto && buf generate
```

Expected: `gen/go/ai/v1/` and `gen/python/ai/v1/` created with `.pb.go`, `_grpc.pb.go`, `_pb2.py`, `_pb2_grpc.py` files.

- [ ] **Step 3: Create go.mod for generated proto stubs (needed for Go module resolution)**

```bash
cd gen/go && go mod init ai-design-platform/gen/go
```

Verify:
```
module ai-design-platform/gen/go

go 1.22
```

- [ ] **Step 4: Verify generated files exist**

Run: `ls gen/go/ai/v1/generation.pb.go gen/go/ai/v1/generation_grpc.pb.go gen/python/ai/v1/generation_pb2.py gen/python/ai/v1/generation_pb2_grpc.py`
Expected: All four files exist.

---

### Task 4: Docker Compose — Local Dev Environment

**Files:**
- Create: `docker-compose.yml`

- [ ] **Step 1: Create docker-compose.yml**

```yaml
version: "3.8"

services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: aiplatform
      POSTGRES_PASSWORD: aiplatform
      POSTGRES_DB: aiplatform
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U aiplatform"]
      interval: 5s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 5

  ai-service:
    build:
      context: ./ai-service
      dockerfile: Dockerfile
    ports:
      - "50051:50051"
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY:-}
      - OPENAI_API_KEY=${OPENAI_API_KEY:-}
      - LOG_LEVEL=DEBUG
    depends_on:
      redis:
        condition: service_healthy
    volumes:
      - ./gen/python:/gen/python:ro
    restart: unless-stopped

  gateway:
    build:
      context: .            # repo root — needs access to gen/go/
      dockerfile: gateway/Dockerfile
    ports:
      - "8080:8080"
    environment:
      - SERVER_PORT=8080
      - AI_SERVICE_ADDR=ai-service:50051
      - DATABASE_URL=postgres://aiplatform:aiplatform@postgres:5432/aiplatform?sslmode=disable
      - REDIS_ADDR=redis:6379
      - LOG_LEVEL=debug
    depends_on:
      postgres:
        condition: service_healthy
      ai-service:
        condition: service_started
    restart: unless-stopped

volumes:
  pgdata:
```

---

### Task 5: Python AI Service — Project Setup

**Files:**
- Create: `ai-service/pyproject.toml`
- Create: `ai-service/app/__init__.py`
- Create: `ai-service/app/services/__init__.py`
- Create: `ai-service/app/services/llm/__init__.py`
- Create: `ai-service/app/services/generation/__init__.py`
- Create: `ai-service/Dockerfile`

- [ ] **Step 1: Create pyproject.toml**

```toml
[project]
name = "ai-service"
version = "0.1.0"
description = "AI Design Platform — AI Services"
requires-python = ">=3.12"
dependencies = [
    "grpcio>=1.62",
    "protobuf>=5.26",
    "anthropic>=0.30",
    "openai>=1.30",
    "structlog>=24.1",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "grpcio-tools>=1.62",
]
```

- [ ] **Step 2: Create empty __init__.py files**

```
ai-service/app/__init__.py
ai-service/app/services/__init__.py
ai-service/app/services/llm/__init__.py
ai-service/app/services/generation/__init__.py
```

Each is an empty file.

- [ ] **Step 3: Create ai-service/Dockerfile**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[dev]"

# Copy application code
COPY app/ ./app/

# Generated proto stubs are mounted at runtime via docker-compose volume
# The /gen/python path must be in PYTHONPATH for imports
ENV PYTHONPATH="/app:/gen/python"
ENV PYTHONUNBUFFERED=1

EXPOSE 50051

CMD ["python", "-m", "app.main"]
```

---

### Task 6: Python — LLM Provider Abstraction

**Files:**
- Create: `ai-service/app/services/llm/provider.py`
- Create: `ai-service/app/services/llm/mock.py`

- [ ] **Step 1: Write abstract provider interface**

Create `ai-service/app/services/llm/provider.py`:

```python
"""Abstract LLM provider interface."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMConfig:
    """Configuration for an LLM generation request."""
    temperature: float = 0.7
    max_tokens: int = 4096
    top_p: float = 1.0
    stop_sequences: list[str] = field(default_factory=list)


@dataclass
class Message:
    """A chat message."""
    role: str       # "system" | "user" | "assistant"
    content: str


@dataclass
class TokenEvent:
    """A single token from streaming generation."""
    text: str
    index: int


@dataclass
class ToolCallEvent:
    """A tool call request from the LLM."""
    call_id: str
    name: str
    arguments: str  # JSON string


@dataclass
class CompleteEvent:
    """Signals generation completion."""
    finish_reason: str  # "stop" | "length" | "cancelled"
    usage: dict[str, int]  # {"prompt_tokens": N, "completion_tokens": M, "total_tokens": T}


type StreamEvent = TokenEvent | ToolCallEvent | CompleteEvent


class LLMProvider(ABC):
    """Abstract base for LLM providers (OpenAI, Anthropic, etc.)."""

    @abstractmethod
    async def stream_generate(
        self,
        model: str,
        messages: list[Message],
        config: LLMConfig | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Stream tokens from the LLM. Yields TokenEvent, ToolCallEvent, or CompleteEvent."""
        ...

    @abstractmethod
    async def cancel(self) -> None:
        """Cancel the current generation."""
        ...
```

- [ ] **Step 2: Write mock provider for development/testing**

Create `ai-service/app/services/llm/mock.py`:

```python
"""Mock LLM provider for development and testing."""

import asyncio
from collections.abc import AsyncIterator

from app.services.llm.provider import (
    CompleteEvent,
    LLMConfig,
    LLMProvider,
    Message,
    StreamEvent,
    TokenEvent,
)


class MockLLMProvider(LLMProvider):
    """Returns canned responses with simulated delay. No real API calls."""

    def __init__(self) -> None:
        self._cancelled = False

    async def stream_generate(
        self,
        model: str,
        messages: list[Message],
        config: LLMConfig | None = None,
    ) -> AsyncIterator[StreamEvent]:
        self._cancelled = False

        # Get the last user message to echo back a mock response
        user_content = ""
        for m in reversed(messages):
            if m.role == "user":
                user_content = m.content
                break

        mock_response = (
            f"你好！这是 Mock AI 的回复。你的问题是：「{user_content[:50]}...」"
            if len(user_content) > 50
            else f"你好！这是 Mock AI 的回复。你的问题是：「{user_content}」"
        )

        # Simulate token-by-token streaming with delay
        chars = list(mock_response)
        batch_size = 3  # send a few chars per token
        for i in range(0, len(chars), batch_size):
            if self._cancelled:
                yield CompleteEvent(
                    finish_reason="cancelled",
                    usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                )
                return

            token_text = "".join(chars[i : i + batch_size])
            yield TokenEvent(text=token_text, index=i // batch_size)
            await asyncio.sleep(0.05)  # simulate generation latency

        yield CompleteEvent(
            finish_reason="stop",
            usage={
                "prompt_tokens": len(user_content) // 4,
                "completion_tokens": len(mock_response) // 4,
                "total_tokens": (len(user_content) + len(mock_response)) // 4,
            },
        )

    async def cancel(self) -> None:
        self._cancelled = True
```

- [ ] **Step 3: Write tests for mock provider**

Create `ai-service/tests/__init__.py` (empty).

Create `ai-service/tests/test_mock_provider.py`:

```python
"""Tests for MockLLMProvider."""

import pytest

from app.services.llm.mock import MockLLMProvider
from app.services.llm.provider import (
    CompleteEvent,
    LLMConfig,
    Message,
    TokenEvent,
)


@pytest.mark.asyncio
async def test_mock_provider_streams_tokens():
    """Mock provider should yield tokens followed by a complete event."""
    provider = MockLLMProvider()
    messages = [Message(role="user", content="Hello")]

    events = []
    async for event in provider.stream_generate("mock-model", messages):
        events.append(event)

    assert len(events) >= 2  # at least one token + complete
    assert isinstance(events[0], TokenEvent)
    assert isinstance(events[-1], CompleteEvent)
    assert events[-1].finish_reason == "stop"


@pytest.mark.asyncio
async def test_mock_provider_cancellation():
    """Cancellation should yield a CompleteEvent with finish_reason='cancelled'."""
    provider = MockLLMProvider()
    messages = [Message(role="user", content="Hello" * 100)]  # long message = more tokens

    events = []
    async for event in provider.stream_generate("mock-model", messages):
        events.append(event)
        if len(events) == 1:
            await provider.cancel()
            break

    # Drain any remaining events
    async for event in provider.stream_generate("mock-model", messages):
        events.append(event)
        break  # Just get the cancelled complete event

    assert any(
        isinstance(e, CompleteEvent) and e.finish_reason == "cancelled"
        for e in events
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ai-service && pip install -e ".[dev]" && python -m pytest tests/test_mock_provider.py -v`
Expected: 2 tests PASS.

```
test_mock_provider_streams_tokens PASSED
test_mock_provider_cancellation PASSED
```

---

### Task 7: Python — gRPC Generation Service

**Files:**
- Create: `ai-service/app/services/generation/servicer.py`
- Create: `ai-service/tests/test_generation_servicer.py`

- [ ] **Step 1: Write GenerationService gRPC implementation**

Create `ai-service/app/services/generation/servicer.py`:

```python
"""gRPC GenerationService implementation."""

import logging
from typing import AsyncIterator

import grpc
from ai.v1.generation_pb2 import (
    CancelRequest,
    CancelResponse,
    GenerateRequest,
    GenerateResponse,
    GenerationComplete,
    GenerationError,
    Token,
)
from ai.v1.generation_pb2_grpc import GenerationServiceServicer

from app.services.llm.mock import MockLLMProvider
from app.services.llm.provider import (
    CompleteEvent,
    LLMConfig,
    LLMProvider,
    Message,
    TokenEvent,
    ToolCallEvent,
)

logger = logging.getLogger(__name__)


class GenerationServicer(GenerationServiceServicer):
    """Handles LLM generation requests via gRPC server-streaming."""

    def __init__(self, llm_provider: LLMProvider | None = None) -> None:
        self._llm = llm_provider or MockLLMProvider()
        self._active_generations: dict[str, str] = {}  # generation_id -> "running"|"cancelling"

    async def StreamGenerate(
        self,
        request: GenerateRequest,
        context: grpc.aio.ServicerContext,
    ) -> AsyncIterator[GenerateResponse]:
        """Server-streaming RPC: streams tokens from LLM to caller."""
        generation_id = request.generation_id
        self._active_generations[generation_id] = "running"

        # Convert proto messages to domain messages
        messages = [
            Message(role=m.role, content=m.content)
            for m in request.messages
        ]

        config = LLMConfig(
            temperature=request.config.temperature if request.config.temperature else 0.7,
            max_tokens=request.config.max_tokens if request.config.max_tokens else 4096,
            top_p=request.config.top_p if request.config.top_p else 1.0,
            stop_sequences=list(request.config.stop_sequences),
        )

        try:
            async for event in self._llm.stream_generate(
                model=request.model or "claude-sonnet-4-6",
                messages=messages,
                config=config,
            ):
                # Check for cancellation
                if context.cancelled() or self._active_generations.get(generation_id) == "cancelling":
                    await self._llm.cancel()
                    yield GenerateResponse(
                        complete=GenerationComplete(
                            finish_reason="cancelled",
                            usage=None,
                        )
                    )
                    return

                if isinstance(event, TokenEvent):
                    yield GenerateResponse(
                        token=Token(text=event.text, index=event.index)
                    )
                elif isinstance(event, ToolCallEvent):
                    yield GenerateResponse(
                        tool_call=ai.v1.generation_pb2.ToolCall(
                            id=event.call_id,
                            name=event.name,
                            arguments=event.arguments,
                        )
                    )
                elif isinstance(event, CompleteEvent):
                    yield GenerateResponse(
                        complete=GenerationComplete(
                            finish_reason=event.finish_reason,
                            usage=ai.v1.generation_pb2.Usage(
                                prompt_tokens=event.usage.get("prompt_tokens", 0),
                                completion_tokens=event.usage.get("completion_tokens", 0),
                                total_tokens=event.usage.get("total_tokens", 0),
                            ) if event.usage else None,
                        )
                    )
        except Exception as e:
            logger.exception("Generation failed: generation_id=%s", generation_id)
            yield GenerateResponse(
                error=GenerationError(code="INTERNAL", message=str(e))
            )
        finally:
            self._active_generations.pop(generation_id, None)

    async def CancelGeneration(
        self,
        request: CancelRequest,
        context: grpc.aio.ServicerContext,
    ) -> CancelResponse:
        """Cancel an in-progress generation."""
        gid = request.generation_id
        if gid in self._active_generations:
            self._active_generations[gid] = "cancelling"
            await self._llm.cancel()
            return CancelResponse(success=True)
        return CancelResponse(success=False)
```

- [ ] **Step 2: Write tests for GenerationServicer**

Create `ai-service/tests/test_generation_servicer.py`:

```python
"""Tests for GenerationServicer gRPC implementation."""

from unittest.mock import AsyncMock, MagicMock

import grpc
import pytest
from ai.v1.generation_pb2 import (
    CancelRequest,
    GenerateRequest,
    GenerationConfig,
    Message as ProtoMessage,
)

from app.services.generation.servicer import GenerationServicer
from app.services.llm.provider import CompleteEvent, TokenEvent


@pytest.mark.asyncio
async def test_stream_generate_yields_tokens_and_complete():
    """StreamGenerate should convert LLM events to proto responses."""
    # Arrange: mock provider that yields one token then completes
    mock_provider = MagicMock()
    mock_provider.stream_generate = MagicMock()
    mock_provider.stream_generate.return_value = __aiter_with_items([
        TokenEvent(text="Hello", index=0),
        CompleteEvent(finish_reason="stop", usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}),
    ])

    servicer = GenerationServicer(llm_provider=mock_provider)
    context = MagicMock(spec=grpc.aio.ServicerContext)
    context.cancelled.return_value = False

    request = GenerateRequest(
        generation_id="test-123",
        model="mock-model",
        messages=[ProtoMessage(role="user", content="Hi")],
        config=GenerationConfig(temperature=0.5, max_tokens=100),
    )

    # Act
    responses = []
    async for resp in servicer.StreamGenerate(request, context):
        responses.append(resp)

    # Assert
    assert len(responses) == 2
    assert responses[0].WhichOneof("payload") == "token"
    assert responses[0].token.text == "Hello"
    assert responses[1].WhichOneof("payload") == "complete"
    assert responses[1].complete.finish_reason == "stop"
    assert responses[1].complete.usage.total_tokens == 15


def __aiter_with_items(items: list):
    """Helper: convert a list into an async iterator."""
    async def _gen():
        for item in items:
            yield item
    return _gen()
```

- [ ] **Step 3: Run tests**

Run: `cd ai-service && python -m pytest tests/test_generation_servicer.py -v`
Expected: 1 test PASS.

---

### Task 8: Python — gRPC Server Entry Point

**Files:**
- Create: `ai-service/app/main.py`

- [ ] **Step 1: Write main.py with gRPC server**

Create `ai-service/app/main.py`:

```python
"""AI Service entry point — starts gRPC server for AI generation/agent services."""

import asyncio
import logging
import signal
import sys
from concurrent import futures

import grpc
from ai.v1.generation_pb2_grpc import add_GenerationServiceServicer_to_server

from app.services.generation.servicer import GenerationServicer

logger = logging.getLogger(__name__)


def serve() -> None:
    """Start the gRPC server and block until shutdown."""
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    server = grpc.aio.server(
        futures.ThreadPoolExecutor(max_workers=10),
        options=[
            ("grpc.max_concurrent_streams", 100),
            ("grpc.keepalive_time_ms", 30000),
        ],
    )

    # Register services
    add_GenerationServiceServicer_to_server(GenerationServicer(), server)

    listen_addr = "[::]:50051"
    server.add_insecure_port(listen_addr)

    async def _run() -> None:
        await server.start()
        logger.info("AI gRPC server listening on %s", listen_addr)

        # Graceful shutdown
        stop_event = asyncio.Event()

        def _signal_handler() -> None:
            logger.info("Received shutdown signal")
            stop_event.set()

        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _signal_handler)
            except NotImplementedError:
                # Windows: signal handlers only work in main thread
                signal.signal(sig, lambda *_: stop_event.set())

        await stop_event.wait()
        await server.stop(grace=5)
        logger.info("Server stopped")

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    serve()
```

- [ ] **Step 2: Verify the server starts**

Run: `cd ai-service && pip install -e ".[dev]" && python -m app.main &`
Wait 2 seconds.
Run: `curl -v http://localhost:50051` (will fail with HTTP but confirms port is open)
Expected: gRPC server starts, logs "AI gRPC server listening on [::]:50051".
Then stop it: `kill %1`

---

### Task 9: Go Gateway — Project Setup & Config

**Files:**
- Create: `gateway/go.mod`
- Create: `gateway/internal/config/config.go`
- Create: `gateway/Dockerfile`

- [ ] **Step 1: Initialize Go module with replace directive for proto stubs**

Run:
```bash
cd gateway && go mod init ai-design-platform/gateway
```

Then add a `replace` directive to resolve the generated proto imports.
Run:
```bash
cd gateway && go mod edit -replace ai-design-platform/gen/go=../gen/go
```

Verify `gateway/go.mod` contains:
```
module ai-design-platform/gateway

go 1.22

replace ai-design-platform/gen/go => ../gen/go
```

- [ ] **Step 2: Create config package**

Create `gateway/internal/config/config.go`:

```go
package config

import (
	"fmt"
	"os"
	"strings"
)

// Config holds all gateway configuration.
type Config struct {
	ServerPort    string
	AIServiceAddr string
	DatabaseURL   string
	RedisAddr     string
	LogLevel      string
}

// Load reads configuration from environment variables with defaults.
func Load() (*Config, error) {
	cfg := &Config{
		ServerPort:    getEnv("SERVER_PORT", "8080"),
		AIServiceAddr: getEnv("AI_SERVICE_ADDR", "localhost:50051"),
		DatabaseURL:   getEnv("DATABASE_URL", "postgres://aiplatform:aiplatform@localhost:5432/aiplatform?sslmode=disable"),
		RedisAddr:     getEnv("REDIS_ADDR", "localhost:6379"),
		LogLevel:      getEnv("LOG_LEVEL", "info"),
	}

	if strings.TrimSpace(cfg.AIServiceAddr) == "" {
		return nil, fmt.Errorf("AI_SERVICE_ADDR is required")
	}

	return cfg, nil
}

func getEnv(key, defaultVal string) string {
	if val := os.Getenv(key); val != "" {
		return val
	}
	return defaultVal
}
```

- [ ] **Step 3: Create gateway/Dockerfile**

```dockerfile
FROM golang:1.22-alpine AS builder

WORKDIR /build

# Copy Go module files (paths relative to repo root — build context is .)
COPY gateway/go.mod gateway/go.sum ./
RUN go mod download

# Copy gateway source
COPY gateway/cmd/ ./cmd/
COPY gateway/internal/ ./internal/

# Copy generated proto stubs (needed at compile time)
COPY gen/go/ /gen/go/

RUN CGO_ENABLED=0 go build -o /server ./cmd/server

FROM alpine:3.19
RUN apk add --no-cache ca-certificates
COPY --from=builder /server /server
EXPOSE 8080
CMD ["/server"]
```

---

### Task 10: Go Gateway — gRPC Client to Python AI Service

**Files:**
- Create: `gateway/internal/client/ai.go`

- [ ] **Step 1: Write gRPC client for AI service**

Create `gateway/internal/client/ai.go`:

```go
package client

import (
	"context"
	"fmt"
	"io"
	"log/slog"

	pb "ai-design-platform/gen/go/ai/v1"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
)

// AIClient wraps the gRPC connection to the Python AI service.
type AIClient struct {
	conn   *grpc.ClientConn
	genCli pb.GenerationServiceClient
}

// NewAIClient creates a new gRPC client connected to the AI service.
func NewAIClient(ctx context.Context, addr string) (*AIClient, error) {
	conn, err := grpc.DialContext(ctx, addr,
		grpc.WithTransportCredentials(insecure.NewCredentials()),
		grpc.WithBlock(),
	)
	if err != nil {
		return nil, fmt.Errorf("failed to connect to AI service at %s: %w", addr, err)
	}

	slog.Info("Connected to AI service", "addr", addr)
	return &AIClient{
		conn:   conn,
		genCli: pb.NewGenerationServiceClient(conn),
	}, nil
}

// StreamGenerate opens a server-streaming gRPC call for AI generation.
// Returns a receive-only channel of GenerateResponse events and an error channel.
func (c *AIClient) StreamGenerate(
	ctx context.Context,
	req *pb.GenerateRequest,
) (pb.GenerationService_StreamGenerateClient, error) {
	stream, err := c.genCli.StreamGenerate(ctx, req)
	if err != nil {
		return nil, fmt.Errorf("StreamGenerate RPC failed: %w", err)
	}
	return stream, nil
}

// CancelGeneration cancels an in-progress generation in the AI service.
func (c *AIClient) CancelGeneration(ctx context.Context, generationID, reason string) error {
	_, err := c.genCli.CancelGeneration(ctx, &pb.CancelRequest{
		GenerationId: generationID,
		Reason:       reason,
	})
	return err
}

// Close shuts down the gRPC connection.
func (c *AIClient) Close() error {
	return c.conn.Close()
}

// ReceiveAll reads all responses from a stream into a channel (for testing).
func ReceiveAll(stream pb.GenerationService_StreamGenerateClient) ([]*pb.GenerateResponse, error) {
	var responses []*pb.GenerateResponse
	for {
		resp, err := stream.Recv()
		if err == io.EOF {
			break
		}
		if err != nil {
			return responses, fmt.Errorf("stream receive error: %w", err)
		}
		responses = append(responses, resp)
	}
	return responses, nil
}
```

- [ ] **Step 2: Run `go mod tidy` to fetch dependencies**

Run: `cd gateway && go mod tidy`
Expected: Downloads gRPC, protobuf, gin dependencies. No errors.

---

### Task 11: Go Gateway — Middleware

**Files:**
- Create: `gateway/internal/middleware/logging.go`
- Create: `gateway/internal/middleware/auth.go`

- [ ] **Step 1: Create logging middleware**

Create `gateway/internal/middleware/logging.go`:

```go
package middleware

import (
	"log/slog"
	"time"

	"github.com/gin-gonic/gin"
)

// Logging returns a Gin middleware that logs request method, path, status, and duration.
func Logging() gin.HandlerFunc {
	return func(c *gin.Context) {
		start := time.Now()
		path := c.Request.URL.Path
		method := c.Request.Method

		c.Next()

		duration := time.Since(start)
		status := c.Writer.Status()

		slog.Info("request",
			"method", method,
			"path", path,
			"status", status,
			"duration_ms", duration.Milliseconds(),
			"client_ip", c.ClientIP(),
		)
	}
}
```

- [ ] **Step 2: Create auth middleware (stub — returns a placeholder user for now)**

Create `gateway/internal/middleware/auth.go`:

```go
package middleware

import (
	"net/http"

	"github.com/gin-gonic/gin"
)

// User is a placeholder type for authenticated user info.
type User struct {
	ID   string
	Name string
}

const userKey = "user"

// Auth returns a middleware that validates JWT tokens.
// Phase 1: stub — accepts any request and sets a placeholder user.
// Phase 2: real JWT validation.
func Auth() gin.HandlerFunc {
	return func(c *gin.Context) {
		// TODO(phase2): Validate JWT from Authorization header
		authHeader := c.GetHeader("Authorization")
		if authHeader == "" {
			// For now, allow unauthenticated requests with a placeholder user
			c.Set(userKey, User{ID: "anonymous", Name: "Anonymous"})
			c.Next()
			return
		}

		// Placeholder: treat token as user ID
		c.Set(userKey, User{ID: authHeader, Name: authHeader})
		c.Next()
	}
}

// GetUser extracts the authenticated user from the Gin context.
func GetUser(c *gin.Context) (User, bool) {
	u, exists := c.Get(userKey)
	if !exists {
		return User{}, false
	}
	user, ok := u.(User)
	return user, ok
}
```

---

### Task 12: Go Gateway — Handlers (Health + Chat SSE)

**Files:**
- Create: `gateway/internal/handler/health.go`
- Create: `gateway/internal/handler/chat.go`

- [ ] **Step 1: Create health check handler**

Create `gateway/internal/handler/health.go`:

```go
package handler

import (
	"net/http"

	"github.com/gin-gonic/gin"
)

// HealthHandler serves health check endpoints.
type HealthHandler struct{}

// NewHealthHandler creates a new HealthHandler.
func NewHealthHandler() *HealthHandler {
	return &HealthHandler{}
}

// Health returns 200 OK — used for liveness probes.
func (h *HealthHandler) Health(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{
		"status": "ok",
	})
}

// Ready checks if the gateway can connect to its dependencies.
func (h *HealthHandler) Ready(c *gin.Context) {
	// TODO(phase2): check gRPC connection + DB + Redis
	c.JSON(http.StatusOK, gin.H{
		"status": "ready",
	})
}
```

- [ ] **Step 2: Create Chat SSE handler**

Create `gateway/internal/handler/chat.go`:

```go
package handler

import (
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"

	pb "ai-design-platform/gen/go/ai/v1"
	"ai-design-platform/gateway/internal/client"
	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
)

// ChatRequest is the JSON body for the chat stream endpoint.
type ChatRequest struct {
	Model    string        `json:"model" binding:"required"`
	Messages []ChatMessage `json:"messages" binding:"required"`
}

// ChatMessage represents a single message in the conversation.
type ChatMessage struct {
	Role    string `json:"role" binding:"required"`
	Content string `json:"content" binding:"required"`
}

// ChatHandler handles AI chat streaming endpoints.
type ChatHandler struct {
	aiClient *client.AIClient
}

// NewChatHandler creates a new ChatHandler.
func NewChatHandler(aiClient *client.AIClient) *ChatHandler {
	return &ChatHandler{aiClient: aiClient}
}

// StreamChat handles SSE-based streaming AI chat.
// POST /api/v1/chat/stream
func (h *ChatHandler) StreamChat(c *gin.Context) {
	var req ChatRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	generationID := uuid.New().String()

	// Build gRPC request
	pbMessages := make([]*pb.Message, len(req.Messages))
	for i, m := range req.Messages {
		pbMessages[i] = &pb.Message{
			Role:    m.Role,
			Content: m.Content,
		}
	}

	grpcReq := &pb.GenerateRequest{
		GenerationId: generationID,
		Model:        req.Model,
		Messages:     pbMessages,
		Config: &pb.GenerationConfig{
			Temperature: 0.7,
			MaxTokens:   4096,
		},
	}

	// Open gRPC stream to AI service
	stream, err := h.aiClient.StreamGenerate(c.Request.Context(), grpcReq)
	if err != nil {
		slog.Error("Failed to start gRPC stream", "error", err)
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "AI service unavailable"})
		return
	}

	// Set SSE headers
	c.Header("Content-Type", "text/event-stream")
	c.Header("Cache-Control", "no-cache")
	c.Header("Connection", "keep-alive")
	c.Header("X-Accel-Buffering", "no")
	c.Status(http.StatusOK)

	// Send generation_id as first event so client can cancel
	c.SSEvent("meta", gin.H{"generation_id": generationID})
	c.Writer.Flush()

	// Bridge gRPC stream → SSE
	c.Stream(func(w io.Writer) bool {
		resp, err := stream.Recv()
		if err == io.EOF {
			c.SSEvent("done", "[DONE]")
			return false
		}
		if err != nil {
			slog.Error("gRPC stream error", "error", err)
			c.SSEvent("error", gin.H{"message": err.Error()})
			return false
		}

		switch payload := resp.Payload.(type) {
		case *pb.GenerateResponse_Token:
			c.SSEvent("token", gin.H{"text": payload.Token.Text, "index": payload.Token.Index})
		case *pb.GenerateResponse_ToolCall_:
			c.SSEvent("tool_call", gin.H{
				"id":        payload.ToolCall.Id,
				"name":      payload.ToolCall.Name,
				"arguments": payload.ToolCall.Arguments,
			})
		case *pb.GenerateResponse_Complete:
			completeJSON, _ := json.Marshal(gin.H{
				"finish_reason": payload.Complete.FinishReason,
			})
			c.SSEvent("complete", string(completeJSON))
			return false
		case *pb.GenerateResponse_Error:
			c.SSEvent("error", gin.H{"code": payload.Error.Code, "message": payload.Error.Message})
			return false
		default:
			slog.Warn("Unknown response payload type", "type", fmt.Sprintf("%T", resp.Payload))
		}
		return true
	})
}

// CancelChat cancels an in-progress generation.
// POST /api/v1/chat/cancel/:id
func (h *ChatHandler) CancelChat(c *gin.Context) {
	generationID := c.Param("id")
	if generationID == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "generation_id is required"})
		return
	}

	if err := h.aiClient.CancelGeneration(c.Request.Context(), generationID, "user_cancelled"); err != nil {
		slog.Error("Failed to cancel generation", "generation_id", generationID, "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to cancel"})
		return
	}

	c.JSON(http.StatusOK, gin.H{"status": "cancelled", "generation_id": generationID})
}
```

---

### Task 13: Go Gateway — Main Entry Point & Wiring

**Files:**
- Create: `gateway/cmd/server/main.go`

- [ ] **Step 1: Write main.go — wires everything together**

Create `gateway/cmd/server/main.go`:

```go
package main

import (
	"context"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"ai-design-platform/gateway/internal/client"
	"ai-design-platform/gateway/internal/config"
	"ai-design-platform/gateway/internal/handler"
	"ai-design-platform/gateway/internal/middleware"

	"github.com/gin-gonic/gin"
)

func main() {
	// Logger
	slog.SetDefault(slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{
		Level: slog.LevelInfo,
	})))

	// Config
	cfg, err := config.Load()
	if err != nil {
		slog.Error("Failed to load config", "error", err)
		os.Exit(1)
	}

	// gRPC client to AI service
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	aiClient, err := client.NewAIClient(ctx, cfg.AIServiceAddr)
	if err != nil {
		slog.Error("Failed to connect to AI service", "error", err)
		os.Exit(1)
	}
	defer aiClient.Close()

	// Handlers
	healthH := handler.NewHealthHandler()
	chatH := handler.NewChatHandler(aiClient)

	// Gin router
	gin.SetMode(gin.ReleaseMode)
	r := gin.New()
	r.Use(gin.Recovery())
	r.Use(middleware.Logging())
	r.Use(middleware.Auth())

	// Routes
	r.GET("/health", healthH.Health)
	r.GET("/ready", healthH.Ready)

	api := r.Group("/api/v1")
	{
		api.POST("/chat/stream", chatH.StreamChat)
		api.POST("/chat/cancel/:id", chatH.CancelChat)
	}

	// HTTP server
	srv := &http.Server{
		Addr:         ":" + cfg.ServerPort,
		Handler:      r,
		ReadTimeout:  10 * time.Second,
		WriteTimeout: 5 * time.Minute, // SSE connections are long-lived
		IdleTimeout:  2 * time.Minute,
	}

	// Graceful shutdown
	go func() {
		quit := make(chan os.Signal, 1)
		signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
		<-quit
		slog.Info("Shutting down server...")

		shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer shutdownCancel()

		if err := srv.Shutdown(shutdownCtx); err != nil {
			slog.Error("Server forced to shutdown", "error", err)
		}
	}()

	slog.Info("Gateway server starting", "port", cfg.ServerPort)
	if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		slog.Error("Server failed", "error", err)
		os.Exit(1)
	}
	slog.Info("Server stopped")
}
```

- [ ] **Step 2: Verify Go project compiles**

Run: `cd gateway && go mod tidy && go build ./cmd/server`
Expected: No errors. Binary `cmd/server/server` created.

---

### Task 14: Anthropic LLM Provider (Real Implementation)

**Files:**
- Create: `ai-service/app/services/llm/anthropic.py`
- Create: `ai-service/tests/test_anthropic_provider.py`

- [ ] **Step 1: Write Anthropic provider**

Create `ai-service/app/services/llm/anthropic.py`:

```python
"""Anthropic (Claude) LLM provider implementation."""

import os
from collections.abc import AsyncIterator

from anthropic import Anthropic, AsyncAnthropic

from app.services.llm.provider import (
    CompleteEvent,
    LLMConfig,
    LLMProvider,
    Message,
    StreamEvent,
    TokenEvent,
    ToolCallEvent,
)


class AnthropicProvider(LLMProvider):
    """LLM provider backed by Anthropic Claude API with streaming."""

    def __init__(self, api_key: str | None = None) -> None:
        key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._client = AsyncAnthropic(api_key=key)
        self._cancel_flag = False

    async def stream_generate(
        self,
        model: str,
        messages: list[Message],
        config: LLMConfig | None = None,
    ) -> AsyncIterator[StreamEvent]:
        self._cancel_flag = False
        cfg = config or LLMConfig()

        # Convert messages to Anthropic format
        system_msg = ""
        anthropic_messages: list[dict[str, str]] = []
        for m in messages:
            if m.role == "system":
                system_msg = m.content
            else:
                anthropic_messages.append({"role": m.role, "content": m.content})

        kwargs: dict = {
            "model": model,
            "messages": anthropic_messages,
            "max_tokens": cfg.max_tokens,
            "temperature": cfg.temperature,
            "stream": True,
        }
        if system_msg:
            kwargs["system"] = system_msg

        index = 0
        try:
            async with self._client.messages.stream(**kwargs) as stream:
                async for event in stream:
                    if self._cancel_flag:
                        yield CompleteEvent(
                            finish_reason="cancelled",
                            usage={},
                        )
                        return

                    if event.type == "content_block_delta":
                        if event.delta.type == "text_delta":
                            yield TokenEvent(text=event.delta.text, index=index)
                            index += 1
                        elif event.delta.type == "input_json_delta":
                            # Tool use partial — accumulate but don't emit individual deltas
                            pass
                    elif event.type == "content_block_start":
                        if event.content_block.type == "tool_use":
                            yield ToolCallEvent(
                                call_id=event.content_block.id,
                                name=event.content_block.name,
                                arguments="",  # arguments come as deltas
                            )
                    elif event.type == "message_stop":
                        pass  # stream is ending

            yield CompleteEvent(
                finish_reason="stop",
                usage={},  # streaming doesn't provide usage in the same way
            )
        except Exception as e:
            if not self._cancel_flag:
                raise
            yield CompleteEvent(finish_reason="cancelled", usage={})

    async def cancel(self) -> None:
        self._cancel_flag = True
```

- [ ] **Step 2: Write Anthropic provider tests (requires API key — skip in CI)**

Create `ai-service/tests/test_anthropic_provider.py`:

```python
"""Tests for Anthropic provider. Requires ANTHROPIC_API_KEY env var."""

import os

import pytest

from app.services.llm.anthropic import AnthropicProvider
from app.services.llm.provider import CompleteEvent, Message, TokenEvent


pytestmark = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set",
)


@pytest.mark.asyncio
async def test_anthropic_streams_tokens():
    """Real Anthropic API should return tokens and a complete event."""
    provider = AnthropicProvider()
    messages = [Message(role="user", content='Say "hello world" and nothing else.')]

    events = []
    async for event in provider.stream_generate(
        model="claude-sonnet-4-6",
        messages=messages,
    ):
        events.append(event)

    tokens = [e for e in events if isinstance(e, TokenEvent)]
    completes = [e for e in events if isinstance(e, CompleteEvent)]

    assert len(tokens) > 0, "Should have at least one token"
    assert len(completes) == 1, "Should have exactly one complete event"
    assert completes[0].finish_reason in ("stop", "end_turn")
```

- [ ] **Step 3: Update pyproject.toml with anthropic dependency**

Verify `pyproject.toml` already includes `anthropic>=0.30` (from Task 5). No additional changes needed.

---

### Task 15: End-to-End Integration Verification

- [ ] **Step 1: Build and start all services**

Run: `cd ai-design-platform-server && docker compose up --build -d`

Wait for healthy status.

- [ ] **Step 2: Check health endpoints**

```bash
curl -s http://localhost:8080/health
```
Expected: `{"status":"ok"}`

```bash
curl -s http://localhost:8080/ready
```
Expected: `{"status":"ready"}`

- [ ] **Step 3: Test SSE streaming endpoint with Mock LLM**

```bash
curl -N -X POST http://localhost:8080/api/v1/chat/stream \
  -H "Content-Type: application/json" \
  -d '{
    "model": "mock-model",
    "messages": [
      {"role": "user", "content": "你好，介绍一下你自己"}
    ]
  }'
```

Expected output (SSE stream):
```
event: meta
data: {"generation_id":"..."}

event: token
data: {"index":0,"text":"你好"}

event: token
data: {"index":1,"text":"！这是"}

... (more tokens) ...

event: complete
data: {"finish_reason":"stop"}

event: done
data: [DONE]
```

- [ ] **Step 4: Test cancellation**

In terminal 1:
```bash
# Store the generation_id from /chat/stream and send cancel
curl -s -X POST http://localhost:8080/api/v1/chat/cancel/<generation_id>
```
Expected: `{"generation_id":"...","status":"cancelled"}`

- [ ] **Step 5: Stop services**

```bash
docker compose down
```

---

### Task 16: Project Polish — README & Makefile Finalization

**Files:**
- Modify: `README.md` (update if needed)
- Modify: `Makefile` (verify all targets work)

- [ ] **Step 1: Verify all Makefile targets work**

```bash
make dev-up      # starts everything
make dev-logs    # shows logs (Ctrl+C to exit)
make dev-down    # stops everything
```

- [ ] **Step 2: Final README review**

Ensure README.md contains:
- Architecture diagram (ASCII)
- Quick start instructions
- How to run tests
- How to generate proto stubs
- Environment variables reference

---

## Phase Summary

| Phase | Tasks | Delivers |
|-------|-------|----------|
| Foundation | 1-4 | Project structure, proto contracts, Docker Compose |
| Python AI Service | 5-8 | gRPC server, LLM abstraction, Mock + Anthropic providers, Generation servicer |
| Go Gateway | 9-13 | Gin server, gRPC client, SSE handler, auth/logging middleware |
| Verification | 14-16 | End-to-end streaming flow, cancellation, documentation |
