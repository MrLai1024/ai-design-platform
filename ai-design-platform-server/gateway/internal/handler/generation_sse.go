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

// GraphSSEHandler handles LangGraph streaming via SSE.
type GraphSSEHandler struct {
	aiClient      *client.AIClient
	feedbackStore map[string]string // generation_id -> feedback_text
}

// FeedbackRequest for user feedback on code stage.
type FeedbackRequest struct {
	GenerationID string `json:"generation_id"`
	Stage        string `json:"stage"`
	Feedback     string `json:"feedback"`
}

// GenerationRequest with graph-specific fields.
type GenerationRequest struct {
	Model          string        `json:"model" binding:"required"`
	Messages       []ChatMessage `json:"messages"`
	EnableThinking bool          `json:"enable_thinking"`
	ComponentLib   string        `json:"component_lib"`
	GenerationID   string        `json:"generation_id"`
	Mode           string        `json:"mode"`
	SkipAnalysis   bool          `json:"skip_analysis"`
}

func NewGraphSSEHandler(aiClient *client.AIClient) *GraphSSEHandler {
	return &GraphSSEHandler{aiClient: aiClient, feedbackStore: make(map[string]string)}
}

// StreamGeneration handles POST /api/v1/generation/stream
func (h *GraphSSEHandler) StreamGeneration(c *gin.Context) {
	var req GenerationRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	slog.Info("StreamGeneration request", "mode", req.Mode, "skip_analysis", req.SkipAnalysis, "generation_id", req.GenerationID, "messages", len(req.Messages))

	mode := req.Mode
	if mode == "" {
		mode = "graph"
	}
	generationID := req.GenerationID
	if generationID == "" {
		generationID = newUUID()
	}

	pbMessages := make([]*pb.Message, len(req.Messages))
	for i, m := range req.Messages {
		pbMessages[i] = &pb.Message{
			Role:    m.Role,
			Content: m.Content,
		}
	}

	metadata := map[string]string{
		"mode": mode,
	}
	if req.SkipAnalysis {
		metadata["skip_analysis"] = "true"
	}
	// Inject pending feedback if any
	if fb, ok := h.feedbackStore[generationID]; ok && fb != "" {
		metadata["code_feedback"] = fb
		delete(h.feedbackStore, generationID)
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
		Metadata: metadata,
	}

	stream, err := h.aiClient.StreamGenerate(c.Request.Context(), grpcReq)
	if err != nil {
		slog.Error("Failed to start gRPC stream for graph generation", "error", err)
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "AI service unavailable"})
		return
	}

	c.Header("Content-Type", "text/event-stream")
	c.Header("Cache-Control", "no-cache, no-transform")
	c.Header("Connection", "keep-alive")
	c.Header("X-Accel-Buffering", "no")
	c.Status(http.StatusOK)

	writeSSE(c, "meta", gin.H{"_t": "meta", "generation_id": generationID})
	c.Writer.Flush()

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
			payloadMap := gin.H{
				"_t":    payload.GraphEvent.EventType,
				"stage": payload.GraphEvent.Stage,
			}
			var data map[string]interface{}
			if err := json.Unmarshal([]byte(payload.GraphEvent.Data), &data); err == nil {
				for k, v := range data {
					payloadMap[k] = v
				}
			}
			writeSSE(c, "", payloadMap)
		}
		return true
	})
}

// SubmitFeedback handles POST /api/v1/generation/feedback
func (h *GraphSSEHandler) SubmitFeedback(c *gin.Context) {
	var req FeedbackRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	if req.GenerationID == "" || req.Feedback == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "generation_id and feedback required"})
		return
	}
	h.feedbackStore[req.GenerationID] = req.Feedback
	slog.Info("feedback_stored", "generation_id", req.GenerationID, "feedback_len", len(req.Feedback))
	c.JSON(http.StatusOK, gin.H{"received": true})
}
