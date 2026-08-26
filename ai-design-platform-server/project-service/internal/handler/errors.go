package handler

import (
	"log/slog"
	"net/http"

	"github.com/gin-gonic/gin"
)

// internalError 记录错误日志并返回统一 500 信封响应,供各业务 handler 复用。
func internalError(c *gin.Context, op string, err error) {
	slog.Error(op, "error", err)
	Error(c, http.StatusInternalServerError, CodeInternal, "内部错误")
}
