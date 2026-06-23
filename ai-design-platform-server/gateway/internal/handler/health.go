package handler

import (
	"net/http"

	"github.com/gin-gonic/gin"
)

// HealthHandler serves health check endpoints.
type HealthHandler struct{}

// NewHealthHandler creates a new HealthHandler.
func NewHealthHandler() *HealthHandler {
	return &HealthHandler{}
}

// Health returns 200 OK — used for liveness probes.
func (h *HealthHandler) Health(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{
		"status": "ok",
	})
}

// Ready checks if the gateway can connect to its dependencies.
func (h *HealthHandler) Ready(c *gin.Context) {
	// TODO(phase2): check gRPC connection + DB + Redis
	c.JSON(http.StatusOK, gin.H{
		"status": "ready",
	})
}
