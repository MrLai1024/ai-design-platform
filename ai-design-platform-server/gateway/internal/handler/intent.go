package handler

import (
	"log/slog"
	"net/http"

	"ai-design-platform/gateway/internal/client"

	"github.com/gin-gonic/gin"
)

// IntentRequest is the payload for Manager intent classification.
type IntentRequest struct {
	Text         string `json:"text" binding:"required"`
	Stage        string `json:"stage"`
	GenerationID string `json:"generation_id"`
}

// IntentHandler handles the Manager dialog intent endpoint.
type IntentHandler struct {
	aiClient *client.AIClient
}

// NewIntentHandler 创建一个新的 IntentHandler。
func NewIntentHandler(aiClient *client.AIClient) *IntentHandler {
	return &IntentHandler{aiClient: aiClient}
}

// ClassifyIntent 处理 POST /api/v1/generation/intent
// 轻量 LLM 调用将用户输入分类为 reply_qa / proceed / feedback / escalate / ask_why。
func (h *IntentHandler) ClassifyIntent(c *gin.Context) {
	var req IntentRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	intent, reason, err := h.aiClient.ClassifyIntent(c.Request.Context(), req.Text, req.Stage, req.GenerationID)
	if err != nil {
		slog.Error("ClassifyIntent RPC failed", "error", err)
		c.JSON(http.StatusBadGateway, gin.H{"error": "AI service unavailable"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"intent": intent, "reason": reason})
}
