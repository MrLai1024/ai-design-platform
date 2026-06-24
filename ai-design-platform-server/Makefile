.PHONY: proto-gen proto-clean dev-up dev-down dev-logs build build-gateway build-ai test test-gateway test-ai

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
