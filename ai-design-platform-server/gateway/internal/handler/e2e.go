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

// E2EResultRequest is the payload from the frontend after executing the full
// E2E run (task group 6): one batch per run, forwarded to the AI service's
// ResumeAfterE2E (Test Diagnoser → gate routing), streamed back as SSE.
type E2EResultRequest struct {
	GenerationID string              `json:"generation_id" binding:"required"`
	Results      []client.E2ECaseResult `json:"results" binding:"required"`
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

// RuntimeFeedbackRequest is the payload from the preview iframe console
// capture (Verifier L3 evidence).
type RuntimeFeedbackRequest struct {
	GenerationID string                `json:"generation_id" binding:"required"`
	Errors       []client.RuntimeError `json:"errors"`
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
//
// 前端 Runner 完成整轮执行后一次性提交结果（task group 6）：转发 AI service
// 的 ResumeAfterE2E（Test Diagnoser 三方分类 → e2e gate 路由），GraphEvents
// 以 SSE 流回前端（manager 裁决 / 诊断卡片 / e2e_complete）。
func (h *E2EHandler) SubmitE2EResult(c *gin.Context) {
	var req E2EResultRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	stream, err := h.aiClient.ResumeAfterE2E(c.Request.Context(), req.GenerationID, req.Results)
	if err != nil {
		slog.Error("ResumeAfterE2E stream failed", "generation_id", req.GenerationID, "error", err)
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "AI service unavailable"})
		return
	}

	c.Header("Content-Type", "text/event-stream")
	c.Header("Cache-Control", "no-cache, no-transform")
	c.Header("Connection", "keep-alive")
	c.Header("X-Accel-Buffering", "no")
	c.Status(http.StatusOK)

	c.Stream(func(w io.Writer) bool {
		resp, err := stream.Recv()
		if err == io.EOF {
			writeSSE(c, "done", "[DONE]")
			return false
		}
		if err != nil {
			slog.Error("e2e gRPC stream error", "error", err)
			writeSSE(c, "error", gin.H{"_t": "error", "message": err.Error()})
			return false
		}

		switch payload := resp.Payload.(type) {
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
		case *pb.GenerateResponse_Error:
			writeSSE(c, "error", gin.H{
				"_t":      "error",
				"code":    payload.Error.Code,
				"message": payload.Error.Message,
			})
			return false
		}
		return true
	})
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

// SubmitRuntimeFeedback handles POST /api/v1/generation/runtime-feedback
// 预览 iframe console 捕获 → 转发 AI service → Verifier L3 / Debugger 证据。
func (h *E2EHandler) SubmitRuntimeFeedback(c *gin.Context) {
	var req RuntimeFeedbackRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	received, err := h.aiClient.ReportRuntimeFeedback(c.Request.Context(), req.GenerationID, req.Errors)
	if err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"error": "AI service unavailable"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"received": received})
}
