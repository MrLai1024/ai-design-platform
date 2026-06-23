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
