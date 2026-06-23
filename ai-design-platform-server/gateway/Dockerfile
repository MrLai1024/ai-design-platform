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
