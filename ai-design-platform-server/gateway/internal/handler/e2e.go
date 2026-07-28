package handler

import (
	"net/http"

	"ai-design-platform/gateway/internal/client"

	"github.com/gin-gonic/gin"
)

// E2EResultRequest is the payload from frontend after executing a test case.
type E2EResultRequest struct {
	GenerationID string `json:"generation_id" binding:"required"`
	CaseID       string `json:"case_id" binding:"required"`
	Passed       bool   `json:"passed"`
	Error        string `json:"error,omitempty"`
	Screenshot   string `json:"screenshot,omitempty"`
}

// ConfirmRequest is the payload when user confirms analysis/design stage.
type ConfirmRequest struct {
	GenerationID string `json:"generation_id" binding:"required"`
	Stage        string `json:"stage" binding:"required"`
}

// CompileFeedbackRequest is the payload from the frontend bundler preview.
type CompileFeedbackRequest struct {
	GenerationID string                `json:"generation_id" binding:"required"`
	OK           bool                  `json:"ok"`
	Errors       []client.CompileError `json:"errors"`
}

// E2EHandler handles E2E test result reporting and stage confirmation.
type E2EHandler struct {
	graphHandler *GraphSSEHandler
	aiClient     *client.AIClient
}

func NewE2EHandler(graphHandler *GraphSSEHandler, aiClient *client.AIClient) *E2EHandler {
	return &E2EHandler{graphHandler: graphHandler, aiClient: aiClient}
}

// SubmitE2EResult handles POST /api/v1/e2e/result
func (h *E2EHandler) SubmitE2EResult(c *gin.Context) {
	var req E2EResultRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"status": "received"})
}

// ConfirmStage handles POST /api/v1/generation/confirm
func (h *E2EHandler) ConfirmStage(c *gin.Context) {
	var req ConfirmRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"status": "confirmed", "stage": req.Stage})
}

// SubmitCompileFeedback handles POST /api/v1/generation/compile_feedback
// 前端 esbuild-wasm 打包结果 → 转发 AI service → Executor 消费真实错误。
func (h *E2EHandler) SubmitCompileFeedback(c *gin.Context) {
	var req CompileFeedbackRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	received, err := h.aiClient.ReportCompileFeedback(c.Request.Context(), req.GenerationID, req.OK, req.Errors)
	if err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"error": "AI service unavailable"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"received": received})
}
