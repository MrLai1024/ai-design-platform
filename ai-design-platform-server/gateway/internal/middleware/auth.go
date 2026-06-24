package middleware

import (
	"github.com/gin-gonic/gin"
)

// User 是已认证用户信息的占位符类型。
type User struct {
	ID   string
	Name string
}

const userKey = "user"

// Auth 返回一个验证 JWT 令牌的中间件。
// 第一阶段：桩代码 — 接受任何请求并设置占位用户。
// 第二阶段：真正的 JWT 验证。
func Auth() gin.HandlerFunc {
	return func(c *gin.Context) {
		// TODO(phase2): 从 Authorization 头验证 JWT
		authHeader := c.GetHeader("Authorization")
		if authHeader == "" {
			// 目前，允许未认证的请求并使用占位用户
			c.Set(userKey, User{ID: "anonymous", Name: "Anonymous"})
			c.Next()
			return
		}

		// 占位：将令牌视为用户 ID
		c.Set(userKey, User{ID: authHeader, Name: authHeader})
		c.Next()
	}
}

// GetUser 从 Gin 上下文中提取已认证用户。
func GetUser(c *gin.Context) (User, bool) {
	u, exists := c.Get(userKey)
	if !exists {
		return User{}, false
	}
	user, ok := u.(User)
	return user, ok
}
