package handler

import (
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"strings"

	pb "ai-design-platform/gen/go/ai/v1"
	"ai-design-platform/gateway/internal/client"
	"ai-design-platform/gateway/internal/store"

	"github.com/gin-gonic/gin"
)

// ConversationHandler 处理对话的增删改查和消息流式传输。
type ConversationHandler struct {
	store    *store.ConversationStore
	aiClient *client.AIClient
}

// NewConversationHandler 创建一个新的 ConversationHandler。
func NewConversationHandler(aiClient *client.AIClient) *ConversationHandler {
	return &ConversationHandler{
		store:    store.NewConversationStore(),
		aiClient: aiClient,
	}
}

const (
	maxHistoryRounds = 10
	systemPrompt     = `你是 AI 设计助手，专注于 UI/UX 设计、前端开发和设计系统咨询。
你可以帮助用户进行界面设计、交互设计、组件开发、样式调整等任务。
请用简洁专业的方式回答，优先给出可执行的具体建议。`
)

// trimMessages 裁剪对话历史，避免超出模型上下文窗口。
// 规则：保留首条 system 消息 + 最近 maxRounds 轮对话，中间插入省略提示。
func trimMessages(messages []store.Message, maxRounds int) []*pb.Message {
	hasSystem := len(messages) > 0 && messages[0].Role == "system"

	keepCount := maxRounds * 2 // user + assistant 对
	if hasSystem {
		keepCount++
	}

	totalAllowed := keepCount + 1 // +1 for possible system summary
	if len(messages) <= totalAllowed {
		// 无需裁剪
		out := make([]*pb.Message, len(messages))
		for i, m := range messages {
			out[i] = &pb.Message{Role: m.Role, Content: m.Content}
		}
		return out
	}

	out := make([]*pb.Message, 0, totalAllowed)

	// 保留第一条 system 消息
	if hasSystem {
		out = append(out, &pb.Message{Role: messages[0].Role, Content: messages[0].Content})
	}

	// 插入省略提示
	out = append(out, &pb.Message{Role: "system", Content: "[之前的对话已省略]"})

	// 保留最近的消息
	startIdx := len(messages) - keepCount
	if hasSystem {
		startIdx = len(messages) - (maxRounds * 2)
	}
	for _, m := range messages[startIdx:] {
		out = append(out, &pb.Message{Role: m.Role, Content: m.Content})
	}

	return out
}

// --- 请求 / 响应类型 ---

type createConversationReq struct {
	Title string `json:"title"`
}

type sendMessageReq struct {
	Model          string `json:"model" binding:"required"`
	Content        string `json:"content" binding:"required"`
	EnableThinking bool   `json:"enable_thinking"`
}

// --- Handlers ---

// CreateConversation 创建一个新对话。
// POST /api/v1/conversations
func (h *ConversationHandler) CreateConversation(c *gin.Context) {
	var req createConversationReq
	_ = c.ShouldBindJSON(&req)

	conv := h.store.Create(newUUID(), req.Title)

	c.JSON(http.StatusCreated, gin.H{
		"id":         conv.ID,
		"title":      conv.Title,
		"created_at": conv.CreatedAt,
	})
}

// ListConversations 返回所有对话。
// GET /api/v1/conversations
func (h *ConversationHandler) ListConversations(c *gin.Context) {
	items := h.store.List()
	c.JSON(http.StatusOK, gin.H{
		"conversations": items,
	})
}

// GetConversation 返回包含所有消息的对话。
// GET /api/v1/conversations/:id
func (h *ConversationHandler) GetConversation(c *gin.Context) {
	conv := h.store.Get(c.Param("id"))
	if conv == nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "conversation not found"})
		return
	}
	c.JSON(http.StatusOK, conv)
}

// SendMessage 发送用户消息并通过 SSE 流式传输 AI 响应。
// POST /api/v1/conversations/:id/messages
func (h *ConversationHandler) SendMessage(c *gin.Context) {
	convID := c.Param("id")

	var req sendMessageReq
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	slog.Info("SendMessage", "conv_id", convID, "model", req.Model, "enable_thinking", req.EnableThinking)

	// 验证对话是否存在
	conv := h.store.Get(convID)
	if conv == nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "conversation not found"})
		return
	}

	// 保存用户消息
	userMsgID := newUUID()
	h.store.AddMessage(convID, userMsgID, "user", req.Content)

	// 构建消息历史（含自动注入 system prompt 和裁剪）
	conv = h.store.Get(convID) // 添加新消息后重新获取
	rawMessages := conv.Messages

	// 如果第一条消息不是 system，则在最前面插入 system prompt
	// （仅在内存中注入，不写入 store）
	if len(rawMessages) == 0 || rawMessages[0].Role != "system" {
		rawMessages = append(
			[]store.Message{{Role: "system", Content: systemPrompt}},
			rawMessages...,
		)
	}

	// 裁剪历史消息
	pbMessages := trimMessages(rawMessages, maxHistoryRounds)

	generationID := newUUID()
	grpcReq := &pb.GenerateRequest{
		GenerationId: generationID,
		Model:        req.Model,
		Messages:     pbMessages,
		Config: &pb.GenerationConfig{
			Temperature:    0.7,
			MaxTokens:      2048,
			EnableThinking: req.EnableThinking,
		},
	}

	// 打开 gRPC 流
	stream, err := h.aiClient.StreamGenerate(c.Request.Context(), grpcReq)
	if err != nil {
		slog.Error("Failed to start gRPC stream", "error", err)
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "AI service unavailable"})
		return
	}

	// SSE 头部
	c.Header("Content-Type", "text/event-stream")
	c.Header("Cache-Control", "no-cache, no-transform")
	c.Header("Connection", "keep-alive")
	c.Header("X-Accel-Buffering", "no")
	c.Status(http.StatusOK)

	// 发送元数据
	writeSSE(c, "meta", gin.H{
		"_t":             "meta",
		"generation_id":  generationID,
		"conversation_id": convID,
		"message_id":     userMsgID,
	})
	c.Writer.Flush()

	// 累积 AI 响应
	var fullContent strings.Builder

	// 将 gRPC 流转发为 SSE
	c.Stream(func(w io.Writer) bool {
		resp, err := stream.Recv()
		if err == io.EOF {
			// 保存助手消息
			aiContent := fullContent.String()
			if aiContent != "" {
				h.store.AddMessage(convID, newUUID(), "assistant", aiContent)
			}
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
			// 思考过程 → reasoning 事件
			if payload.Token.ReasoningContent != "" {
				writeSSE(c, "reasoning", gin.H{
					"_t":    "reasoning",
					"text":  payload.Token.ReasoningContent,
					"index": payload.Token.Index,
				})
			}
			// 正常文本 → token 事件
			if payload.Token.Text != "" {
				fullContent.WriteString(payload.Token.Text)
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
			// 完成后保存助手消息
			aiContent := fullContent.String()
			if aiContent != "" {
				h.store.AddMessage(convID, newUUID(), "assistant", aiContent)
			}
			completeJSON, _ := json.Marshal(gin.H{
				"_t":            "complete",
				"finish_reason": payload.Complete.FinishReason,
			})
			writeSSE(c, "complete", string(completeJSON))
			writeSSE(c, "done", "[DONE]")
			return false
		case *pb.GenerateResponse_Error:
			writeSSE(c, "error", gin.H{"_t": "error", "code": payload.Error.Code, "message": payload.Error.Message})
			return false
		default:
			slog.Warn("Unknown response payload type", "type", fmt.Sprintf("%T", resp.Payload))
		}
		return true
	})
}

// DeleteConversation 删除一个对话。
// DELETE /api/v1/conversations/:id
func (h *ConversationHandler) DeleteConversation(c *gin.Context) {
	if ok := h.store.Delete(c.Param("id")); !ok {
		c.JSON(http.StatusNotFound, gin.H{"error": "conversation not found"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"status": "deleted"})
}
