package middleware

import (
	"github.com/gin-gonic/gin"
)

// User is a placeholder type for authenticated user info.
type User struct {
	ID   string
	Name string
}

const userKey = "user"

// Auth returns a middleware that validates JWT tokens.
// Phase 1: stub — accepts any request and sets a placeholder user.
// Phase 2: real JWT validation.
func Auth() gin.HandlerFunc {
	return func(c *gin.Context) {
		// TODO(phase2): Validate JWT from Authorization header
		authHeader := c.GetHeader("Authorization")
		if authHeader == "" {
			// For now, allow unauthenticated requests with a placeholder user
			c.Set(userKey, User{ID: "anonymous", Name: "Anonymous"})
			c.Next()
			return
		}

		// Placeholder: treat token as user ID
		c.Set(userKey, User{ID: authHeader, Name: authHeader})
		c.Next()
	}
}

// GetUser extracts the authenticated user from the Gin context.
func GetUser(c *gin.Context) (User, bool) {
	u, exists := c.Get(userKey)
	if !exists {
		return User{}, false
	}
	user, ok := u.(User)
	return user, ok
}
