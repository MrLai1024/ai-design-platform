package handler

import (
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"strings"

	pb "ai-design-platform/gen/go/ai/v1"
	"ai-design-platform/gateway/internal/client"
	"github.com/gin-gonic/gin"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

// rejectsScopeMarker mirrors ai-service recovery.REJECT_SCOPE_MARKERS —
// 范围确认卡「重新生成/取消」的拒绝标记反馈不进入 Manager 处置 (U9 语义:
// resume 侧 rejects_scope_change 消费), 仅经 feedbackStore 注入。
func rejectsScopeMarker(feedback string) bool {
	text := strings.Trim(feedback, " 。！!？?，,、\t")
	if text == "" {
		return false
	}
	return text == "重新生成" || text == "取消" || text == "重来" || text == "不要" ||
		strings.HasPrefix(text, "重新生成")
}

// GraphAIClient is the subset of *client.AIClient the SSE handler needs —
// an interface so handler tests can stub the feedback disposal (10.1).
type GraphAIClient interface {
	StreamGenerate(ctx context.Context, req *pb.GenerateRequest) (pb.GenerationService_StreamGenerateClient, error)
	ReportUserFeedback(ctx context.Context, generationID, stage, feedback string) (client.UserFeedbackDisposition, error)
}

// GraphSSEHandler handles LangGraph streaming via SSE.
type GraphSSEHandler struct {
	aiClient      GraphAIClient
	feedbackStore map[string]string // generation_id -> feedback_text (scope-reject markers / deferred feedback)
	// 本网关实例服务过的 generation_id (StreamGeneration 登记)。SubmitFeedback
	// 用它在 ai-service NOT_FOUND (runner 丢失, 如 ai-service 重启) 时区分
	// 「曾存在的 generation → 暂存 defer」与「不存在的 generation → 404」。
	seenGenerations map[string]bool
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
	// E2EConfirmed (group 6): explicit confirmation of the designed E2E
	// cases — only the E2EStagePanel 确认按钮 path sets it; chat-intent
	// proceed must not auto-confirm cases.
	E2EConfirmed bool `json:"e2e_confirmed"`
	// Incremental (task group 8): 对已有应用 (同 generation_id 的 .ai-memory)
	// 发起增量开发 — 服务端加载应用记忆 → diff → manifest → 用例处置。
	Incremental bool `json:"incremental"`
	// Regen (task group 8, review I1): 增量确认卡「重新生成」— resume 前
	// 清除当前待确认级产物, 服务端从该级重新计算。
	Regen bool `json:"regen"`
}

func NewGraphSSEHandler(aiClient *client.AIClient) *GraphSSEHandler {
	return &GraphSSEHandler{
		aiClient:        aiClient,
		feedbackStore:   make(map[string]string),
		seenGenerations: make(map[string]bool),
	}
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
	h.seenGenerations[generationID] = true

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
	if req.E2EConfirmed {
		metadata["e2e_confirmed"] = "true"
	}
	if req.Incremental {
		metadata["incremental"] = "true"
	}
	if req.Regen {
		metadata["regen"] = "true"
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
//
// 10.1 迁移: 反馈转发 AI 服务 ReportUserFeedback — Manager 处置 (分类 →
// 问题记录 → 重派/范围确认), 处置结果随 200 返回。无效 generation_id
// (无活跃 runner) → 404。反馈文本仍保留在 feedbackStore — 范围确认卡
// 「重新生成/取消」拒绝标记 (U9) 经 metadata code_feedback 注入 resume。
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
	// U9 范围确认拒绝标记 (「重新生成/取消」) 保留 feedbackStore 注入 —
	// resume 侧 rejects_scope_change 消费, 不走 Manager 处置。
	if rejectsScopeMarker(req.Feedback) {
		h.feedbackStore[req.GenerationID] = req.Feedback
		slog.Info("feedback_stored_scope_reject", "generation_id", req.GenerationID)
		c.JSON(http.StatusOK, gin.H{"received": true, "category": "scope_reject", "result": "rejected"})
		return
	}

	disp, err := h.aiClient.ReportUserFeedback(c.Request.Context(), req.GenerationID, req.Stage, req.Feedback)
	if err != nil {
		if status.Code(err) == codes.NotFound {
			if h.seenGenerations[req.GenerationID] {
				// 曾存在但 runner 丢失 (如 ai-service 重启) — 暂存 feedbackStore,
				// 下次同 generation 流注入 metadata code_feedback, ai-service
				// 消费点 (run/resume 入口兜底) 等价处置。review fix: 停止后
				// 反馈/刷新等场景不得因 runner 瞬时缺失丢反馈。
				h.feedbackStore[req.GenerationID] = req.Feedback
				slog.Warn("feedback_deferred_no_runner", "generation_id", req.GenerationID, "error", err)
				c.JSON(http.StatusOK, gin.H{"received": true, "result": "deferred"})
				return
			}
			slog.Warn("feedback_generation_not_found", "generation_id", req.GenerationID, "error", err)
			c.JSON(http.StatusNotFound, gin.H{"error": "unknown generation_id"})
			return
		}
		slog.Error("feedback_report_failed", "generation_id", req.GenerationID, "error", err)
		c.JSON(http.StatusBadGateway, gin.H{"error": "AI service unavailable"})
		return
	}
	slog.Info("feedback_disposed", "generation_id", req.GenerationID, "category", disp.Category, "result", disp.Result)
	c.JSON(http.StatusOK, gin.H{
		"received":       true,
		"category":       disp.Category,
		"category_label": disp.CategoryLabel,
		"action":         disp.Action,
		"result":         disp.Result,
		"reason":         disp.Reason,
	})
}
