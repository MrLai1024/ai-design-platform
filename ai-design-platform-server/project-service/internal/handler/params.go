package handler

import (
	"net/http"
	"regexp"

	"github.com/gin-gonic/gin"
)

// uuidParamRe 匹配 UUID 的 8-4-4-4-12 十六进制字符串形式。
// 仅用于请求参数的预校验,避免非 UUID 值进入 PostgreSQL uuid 列
// 触发 22P02 错误而返回 500;真实约束仍由数据库 uuid 类型兜底。
var uuidParamRe = regexp.MustCompile(`^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$`)

// parseUUIDParam 解析路径参数中的 UUID 值;格式非法时写 400 并返回 false。
func parseUUIDParam(c *gin.Context, name string) (string, bool) {
	v := c.Param(name)
	if !uuidParamRe.MatchString(v) {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid " + name})
		return "", false
	}
	return v, true
}
