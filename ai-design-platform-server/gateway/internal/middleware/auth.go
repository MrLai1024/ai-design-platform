package middleware

import (
	"net/http"
	"strings"

	"ai-design-platform/gateway/internal/auth"

	"github.com/gin-gonic/gin"
)

// userIDContextKey 是 gin context 中存储已认证用户 id 的键。
const userIDContextKey = "authUserID"

// Auth 校验 Authorization: Bearer <token>,解析出 user_id 注入 gin context。
// token 缺失、格式非法或校验失败时返回 401 并中断请求链。
// 401 响应与 handler 包统一信封一致(业务码 40100 未认证;此处不引用 handler 包以避免 import cycle)。
func Auth(tokens *auth.Manager) gin.HandlerFunc {
	return func(c *gin.Context) {
		token, ok := strings.CutPrefix(c.GetHeader("Authorization"), "Bearer ")
		if !ok || token == "" {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"code": 40100, "msg": "未认证", "data": nil})
			return
		}
		userID, err := tokens.Verify(token)
		if err != nil {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"code": 40100, "msg": "未认证", "data": nil})
			return
		}
		c.Set(userIDContextKey, userID)
		c.Next()
	}
}

// GetUserID 从 gin context 取出 Auth 中间件注入的用户 id。
func GetUserID(c *gin.Context) (string, bool) {
	v, ok := c.Get(userIDContextKey)
	if !ok {
		return "", false
	}
	userID, ok := v.(string)
	return userID, ok
}
