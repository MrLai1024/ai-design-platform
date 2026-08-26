package handler

import (
	"errors"
	"log/slog"
	"net/http"

	"ai-design-platform/project-service/internal/auth"
	"ai-design-platform/project-service/internal/store"

	"github.com/gin-gonic/gin"
)

// maxRegisterAttempts 是账号唯一冲突时换账号重试的最大次数。
const maxRegisterAttempts = 3

// AuthHandler 提供自动注册与当前用户信息接口。
type AuthHandler struct {
	users       *store.Users
	tokens      *auth.Manager
	genAccount  func() (string, error)
	genPassword func() (string, error)
}

// NewAuthHandler 创建 AuthHandler,使用 crypto/rand 随机生成账号与密码。
func NewAuthHandler(users *store.Users, tokens *auth.Manager) *AuthHandler {
	return &AuthHandler{
		users:       users,
		tokens:      tokens,
		genAccount:  auth.RandomAccount,
		genPassword: auth.RandomPassword,
	}
}

// AutoRegister 生成唯一账号与随机密码落 users 表,签发 token 返回。
// 账号唯一约束冲突时换账号重试,最多 maxRegisterAttempts 次。
func (h *AuthHandler) AutoRegister(c *gin.Context) {
	for attempt := 1; attempt <= maxRegisterAttempts; attempt++ {
		account, err := h.genAccount()
		if err != nil {
			internalError(c, "generate account", err)
			return
		}
		password, err := h.genPassword()
		if err != nil {
			internalError(c, "generate password", err)
			return
		}

		user, err := h.users.CreateUser(c.Request.Context(), account, password)
		switch {
		case err == nil:
			token, err := h.tokens.Sign(user.ID)
			if err != nil {
				internalError(c, "sign token", err)
				return
			}
			c.JSON(http.StatusOK, gin.H{
				"account":  user.Account,
				"password": user.Password,
				"token":    token,
			})
			return
		case errors.Is(err, store.ErrAccountConflict):
			slog.Warn("auto-register account conflict, retrying with a new account",
				"account", account, "attempt", attempt)
			continue
		default:
			internalError(c, "create user", err)
			return
		}
	}
	internalError(c, "create user", errors.New("account conflict after max retries"))
}

// Me 返回当前登录用户的账号与密码。
func (h *AuthHandler) Me(c *gin.Context) {
	userID, ok := currentUserID(c)
	if !ok {
		return
	}

	user, err := h.users.GetUserByID(c.Request.Context(), userID)
	if errors.Is(err, store.ErrUserNotFound) {
		c.JSON(http.StatusNotFound, gin.H{"error": "user not found"})
		return
	}
	if err != nil {
		internalError(c, "get user", err)
		return
	}
	c.JSON(http.StatusOK, gin.H{
		"account":  user.Account,
		"password": user.Password,
	})
}
