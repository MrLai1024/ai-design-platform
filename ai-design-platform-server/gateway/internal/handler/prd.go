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

type PRDRequest struct {
	Messages []ChatMessage `json:"messages" binding:"required"`
	Model    string        `json:"model"`
}

type PRDHandler struct {
	aiClient *client.AIClient
}

func NewPRDHandler(aiClient *client.AIClient) *PRDHandler {
	return &PRDHandler{aiClient: aiClient}
}

func (h *PRDHandler) StreamPRD(c *gin.Context) {
	var req PRDRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	if req.Model == "" {
		req.Model = "deepseek-v4-pro"
	}

	generationID := newUUID()

	var qaContext string
	for _, m := range req.Messages {
		qaContext += m.Role + ": " + m.Content + "\n"
	}

	prdPrompt := `你是一个资深产品需求分析师。根据以下需求澄清对话，生成一份完整的需求规格文档（PRD）。

## 文档结构（严格按此顺序输出）
1. **# 需求规格文档**
2. **## 1. 功能概述** — 项目背景、目标用户、核心问题、成功标准、范围边界
3. **## 2. 功能模块** — 按优先级排列（必须有/应该有/锦上添花）
4. **## 3. 页面结构** — 页面树形结构，标注页面类型
5. **## 4. 数据模型** — 核心数据实体及字段定义（表格形式）
6. **## 5. 交互行为** — 关键交互流程说明

## 规则
- 用简洁专业的语言
- 不确定的地方合理推测并标注（待确认）
- 不写代码、不写技术实现、不写组件选择
- 输出纯 Markdown`

	pbMessages := []*pb.Message{
		{Role: "system", Content: prdPrompt},
		{Role: "user", Content: "请根据以下需求澄清对话，生成完整的需求规格文档:\n\n" + qaContext},
	}

	grpcReq := &pb.GenerateRequest{
		GenerationId: generationID,
		Model:        req.Model,
		Messages:     pbMessages,
		Config: &pb.GenerationConfig{
			Temperature:    0.7,
			MaxTokens:      4096,
			EnableThinking: true,
		},
		Metadata: map[string]string{
			"mode":            "chat",
			"enable_thinking": "true",
		},
	}

	stream, err := h.aiClient.StreamGenerate(c.Request.Context(), grpcReq)
	if err != nil {
		slog.Error("Failed to start PRD stream", "error", err)
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
			slog.Error("PRD stream error", "error", err)
			writeSSE(c, "error", gin.H{"_t": "error", "message": err.Error()})
			return false
		}

		switch payload := resp.Payload.(type) {
		case *pb.GenerateResponse_Token:
			if payload.Token.ReasoningContent != "" {
				writeSSE(c, "reasoning", gin.H{
					"_t":   "reasoning",
					"text": payload.Token.ReasoningContent,
				})
			}
			if payload.Token.Text != "" {
				writeSSE(c, "doc_chunk", gin.H{
					"_t":       "doc_chunk",
					"content":  payload.Token.Text,
					"chunk_id": payload.Token.Index,
				})
			}
		case *pb.GenerateResponse_Complete:
			completeJSON, _ := json.Marshal(gin.H{
				"_t":            "prd_complete",
				"finish_reason": payload.Complete.FinishReason,
			})
			writeSSE(c, "prd_complete", string(completeJSON))
			return false
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
