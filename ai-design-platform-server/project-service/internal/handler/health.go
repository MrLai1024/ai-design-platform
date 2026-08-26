// Package handler 提供 project-service 的 HTTP 处理器(健康检查、用户认证、团队与项目管理)。
package handler

import (
	"net/http"

	"github.com/gin-gonic/gin"
)

// HealthHandler 提供健康检查接口。
type HealthHandler struct{}

// NewHealthHandler 创建 HealthHandler。
func NewHealthHandler() *HealthHandler { return &HealthHandler{} }

// Health 返回服务存活状态。
func (h *HealthHandler) Health(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{"status": "ok"})
}
