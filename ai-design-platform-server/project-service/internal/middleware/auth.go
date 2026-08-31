package middleware

import (
	"net/http"
	"regexp"

	"github.com/gin-gonic/gin"
)

// userIDContextKey 是 gin context 中存储已认证用户 id 的键。
const userIDContextKey = "authUserID"

// userIDHeader 是 gateway 注入可信用户身份的请求头。
// project-service 不再解析 JWT,信任 gateway 校验后注入的 X-User-Id。
const userIDHeader = "X-User-Id"

// uuidHeaderRe 匹配 UUID 的 8-4-4-4-12 十六进制字符串形式。
// header 值必须是合法 UUID:users.id 是 uuid 列,非法值落入
// created_by/owner_id 等 uuid 列会触发 22P02 错误而返回 500。
var uuidHeaderRe = regexp.MustCompile(`^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$`)

// Auth 信任 gateway 注入的 X-User-Id header(合法 UUID),将 user_id 注入 gin context。
// header 缺失或非法时返回 401 并中断请求链。
// 401 响应与 handler 包统一信封一致(业务码 40100 未认证;此处不引用 handler 包以避免 import cycle)。
func Auth() gin.HandlerFunc {
	return func(c *gin.Context) {
		userID := c.GetHeader(userIDHeader)
		if !uuidHeaderRe.MatchString(userID) {
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
