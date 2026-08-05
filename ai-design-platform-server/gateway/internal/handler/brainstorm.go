package handler

import (
	"encoding/json"
	"log/slog"
	"net/http"

	"ai-design-platform/gateway/internal/client"

	"github.com/gin-gonic/gin"
)

// BrainstormRequest is the payload for one brainstorm turn.
type BrainstormRequest struct {
	Text         string `json:"text" binding:"required"`
	GenerationID string `json:"generation_id"`
	ItemID       string `json:"item_id"`
}

// BrainstormHandler handles the agenda-driven clarification endpoint.
type BrainstormHandler struct {
	aiClient *client.AIClient
}

// NewBrainstormHandler 创建一个新的 BrainstormHandler。
func NewBrainstormHandler(aiClient *client.AIClient) *BrainstormHandler {
	return &BrainstormHandler{aiClient: aiClient}
}

// Turn 处理 POST /api/v1/generation/brainstorm
// 首轮（不带 generation_id）创建会话并返回其 id；后续轮次带 id 继续。
// 返回离散的 manager_message 卡片（非 SSE）。
func (h *BrainstormHandler) Turn(c *gin.Context) {
	var req BrainstormRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	resp, err := h.aiClient.BrainstormTurn(
		c.Request.Context(), req.Text, req.GenerationID, req.ItemID,
	)
	if err != nil {
		slog.Error("BrainstormTurn RPC failed", "error", err)
		c.JSON(http.StatusBadGateway, gin.H{"error": "AI service unavailable"})
		return
	}

	events := make([]gin.H, 0, len(resp.Events))
	for _, ev := range resp.Events {
		payload := gin.H{"_t": ev.EventType, "stage": ev.Stage}
		var data map[string]interface{}
		if err := json.Unmarshal([]byte(ev.Data), &data); err == nil {
			for k, v := range data {
				payload[k] = v
			}
		}
		events = append(events, payload)
	}

	c.JSON(http.StatusOK, gin.H{
		"generation_id": resp.GenerationId,
		"converged":     resp.Converged,
		"coverage":      resp.Coverage,
		"events":        events,
	})
}
