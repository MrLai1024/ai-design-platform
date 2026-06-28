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

// --- 请求 / 响应类型 ---

type createConversationReq struct {
	Title string `json:"title"`
}

type sendMessageReq struct {
	Model   string `json:"model" binding:"required"`
	Content string `json:"content" binding:"required"`
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

	// 验证对话是否存在
	conv := h.store.Get(convID)
	if conv == nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "conversation not found"})
		return
	}

	// 保存用户消息
	userMsgID := newUUID()
	h.store.AddMessage(convID, userMsgID, "user", req.Content)

	// 使用完整对话历史构建 gRPC 请求
	conv = h.store.Get(convID) // 添加新消息后重新获取
	pbMessages := make([]*pb.Message, 0, len(conv.Messages)+1)
	for _, m := range conv.Messages {
		pbMessages = append(pbMessages, &pb.Message{
			Role:    m.Role,
			Content: m.Content,
		})
	}

	generationID := newUUID()
	grpcReq := &pb.GenerateRequest{
		GenerationId: generationID,
		Model:        req.Model,
		Messages:     pbMessages,
		Config: &pb.GenerationConfig{
			Temperature: 0.7,
			MaxTokens:   4096,
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
	c.Header("Cache-Control", "no-cache")
	c.Header("Connection", "keep-alive")
	c.Header("X-Accel-Buffering", "no")
	c.Status(http.StatusOK)

	// 发送元数据
	c.SSEvent("meta", gin.H{
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
			fullContent.WriteString(payload.Token.Text)
			c.SSEvent("token", gin.H{
				"text":  payload.Token.Text,
				"index": payload.Token.Index,
			})
		case *pb.GenerateResponse_ToolCall:
			c.SSEvent("tool_call", gin.H{
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
				"finish_reason": payload.Complete.FinishReason,
			})
			c.SSEvent("complete", string(completeJSON))
			c.SSEvent("done", "[DONE]")
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

// DeleteConversation 删除一个对话。
// DELETE /api/v1/conversations/:id
func (h *ConversationHandler) DeleteConversation(c *gin.Context) {
	if ok := h.store.Delete(c.Param("id")); !ok {
		c.JSON(http.StatusNotFound, gin.H{"error": "conversation not found"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"status": "deleted"})
}
