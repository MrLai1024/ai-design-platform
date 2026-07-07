package handler

import (
	"encoding/json"
	"io"
	"log/slog"
	"net/http"

	pb "ai-design-platform/gen/go/ai/v1"
	"ai-design-platform/gateway/internal/client"
	"github.com/gin-gonic/gin"
)

// GraphSSEHandler 处理基于 LangGraph 的流式生成事件，通过 SSE 转发给前端。
type GraphSSEHandler struct {
	aiClient *client.AIClient
}

// GenerationRequest 扩展 ChatRequest，增加 graph 专用字段。
type GenerationRequest struct {
	Model          string        `json:"model" binding:"required"`
	Messages       []ChatMessage `json:"messages" binding:"required"`
	EnableThinking bool          `json:"enable_thinking"`
	ComponentLib   string        `json:"component_lib"`
}

// NewGraphSSEHandler 创建一个新的 GraphSSEHandler。
func NewGraphSSEHandler(aiClient *client.AIClient) *GraphSSEHandler {
	return &GraphSSEHandler{aiClient: aiClient}
}

// StreamGeneration 处理基于 SSE 的流式 LangGraph 生成。
// POST /api/v1/generation/stream
func (h *GraphSSEHandler) StreamGeneration(c *gin.Context) {
	var req GenerationRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	generationID := newUUID()

	// 构建 gRPC 请求
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
			Temperature:    0.7,
			MaxTokens:      2048,
			EnableThinking: req.EnableThinking,
		},
		Metadata: map[string]string{
			"mode":          "graph",
			"component_lib": req.ComponentLib,
		},
	}

	// 打开到 AI 服务的 gRPC 流
	stream, err := h.aiClient.StreamGenerate(c.Request.Context(), grpcReq)
	if err != nil {
		slog.Error("Failed to start gRPC stream for graph generation", "error", err)
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "AI service unavailable"})
		return
	}

	// 设置 SSE 头部
	c.Header("Content-Type", "text/event-stream")
	c.Header("Cache-Control", "no-cache, no-transform")
	c.Header("Connection", "keep-alive")
	c.Header("X-Accel-Buffering", "no")
	c.Status(http.StatusOK)

	// 发送 generation_id 作为第一个事件，以便客户端可以追踪
	writeSSE(c, "meta", gin.H{"_t": "meta", "generation_id": generationID})
	c.Writer.Flush()

	// 将 gRPC 流转发为 SSE
	c.Stream(func(w io.Writer) bool {
		resp, err := stream.Recv()
		if err == io.EOF {
			writeSSE(c, "done", "[DONE]")
			return false
		}
		if err != nil {
			slog.Error("gRPC stream error", "error", err)
			writeSSE(c, "error", gin.H{"_t": "error", "message": err.Error()})
			return false
		}

		switch payload := resp.Payload.(type) {
		case *pb.GenerateResponse_Token:
			if payload.Token.ReasoningContent != "" {
				writeSSE(c, "reasoning", gin.H{
					"_t":    "reasoning",
					"text":  payload.Token.ReasoningContent,
					"index": payload.Token.Index,
				})
			}
			if payload.Token.Text != "" {
				writeSSE(c, "token", gin.H{
					"_t":    "token",
					"text":  payload.Token.Text,
					"index": payload.Token.Index,
				})
			}
		case *pb.GenerateResponse_ToolCall:
			writeSSE(c, "tool_call", gin.H{
				"_t":        "tool_call",
				"id":        payload.ToolCall.Id,
				"name":      payload.ToolCall.Name,
				"arguments": payload.ToolCall.Arguments,
			})
		case *pb.GenerateResponse_Complete:
			completeJSON, _ := json.Marshal(gin.H{
				"_t":            "complete",
				"finish_reason": payload.Complete.FinishReason,
			})
			writeSSE(c, "complete", string(completeJSON))
			return false
		case *pb.GenerateResponse_Error:
			writeSSE(c, "error", gin.H{
				"_t":      "error",
				"code":    payload.Error.Code,
				"message": payload.Error.Message,
			})
			return false
		case *pb.GenerateResponse_GraphEvent:
			// 转发 GraphEvent：将 event_type 作为 _t，stage 作为独立字段，
			// 并合并 data JSON 到顶层 payload
			payloadMap := gin.H{
				"_t":    payload.GraphEvent.EventType,
				"stage": payload.GraphEvent.Stage,
			}
			// 将 data JSON 字符串解析并合并到 payload
			var data map[string]interface{}
			if err := json.Unmarshal([]byte(payload.GraphEvent.Data), &data); err == nil {
				for k, v := range data {
					payloadMap[k] = v
				}
			}
			writeSSE(c, "", payloadMap)
		default:
			slog.Warn("Unknown response payload type in graph stream", "type", resp.Payload)
		}
		return true
	})
}
