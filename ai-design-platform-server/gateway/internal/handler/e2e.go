package handler

import (
	"net/http"

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

// E2EHandler handles E2E test result reporting and stage confirmation.
type E2EHandler struct {
	graphHandler *GraphSSEHandler
}

func NewE2EHandler(graphHandler *GraphSSEHandler) *E2EHandler {
	return &E2EHandler{graphHandler: graphHandler}
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
