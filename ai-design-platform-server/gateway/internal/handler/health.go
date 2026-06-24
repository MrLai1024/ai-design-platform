package handler

import (
	"net/http"

	"github.com/gin-gonic/gin"
)

// HealthHandler 提供健康检查端点。
type HealthHandler struct{}

// NewHealthHandler 创建一个新的 HealthHandler。
func NewHealthHandler() *HealthHandler {
	return &HealthHandler{}
}

// Health 返回 200 OK — 用于存活检查。
func (h *HealthHandler) Health(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{
		"status": "ok",
	})
}

// Ready 检查网关是否可以连接到其依赖项。
func (h *HealthHandler) Ready(c *gin.Context) {
	// TODO(phase2): 检查 gRPC 连接、数据库和 Redis
	c.JSON(http.StatusOK, gin.H{
		"status": "ready",
	})
}
