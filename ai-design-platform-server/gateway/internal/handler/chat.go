package handler

import (
	"crypto/rand"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"

	pb "ai-design-platform/gen/go/ai/v1"
	"ai-design-platform/gateway/internal/client"
	"github.com/gin-gonic/gin"
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

	generationID := newUUID()

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
		case *pb.GenerateResponse_ToolCall:
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

// newUUID generates a v4 UUID string using crypto/rand.
func newUUID() string {
	var buf [16]byte
	if _, err := rand.Read(buf[:]); err != nil {
		panic("failed to generate UUID: " + err.Error())
	}
	// Set version 4
	buf[6] = (buf[6] & 0x0f) | 0x40
	// Set variant bits (10xx)
	buf[8] = (buf[8] & 0x3f) | 0x80
	return fmt.Sprintf("%08x-%04x-%04x-%04x-%012x",
		buf[0:4], buf[4:6], buf[6:8], buf[8:10], buf[10:16])
}
