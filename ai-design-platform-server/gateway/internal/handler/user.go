package handler

import (
	"errors"
	"log/slog"
	"net/http"

	"ai-design-platform/gateway/internal/auth"
	"ai-design-platform/gateway/internal/middleware"
	"ai-design-platform/gateway/internal/store"

	"github.com/gin-gonic/gin"
)

// maxRegisterAttempts 是账号唯一冲突时换账号重试的最大次数。
const maxRegisterAttempts = 3

// UserHandler 提供自动注册与当前用户信息接口。
type UserHandler struct {
	users       *store.Users
	tokens      *auth.Manager
	genAccount  func() (string, error)
	genPassword func() (string, error)
}

// NewUserHandler 创建 UserHandler,使用 crypto/rand 随机生成账号与密码。
func NewUserHandler(users *store.Users, tokens *auth.Manager) *UserHandler {
	return &UserHandler{
		users:       users,
		tokens:      tokens,
		genAccount:  auth.RandomAccount,
		genPassword: auth.RandomPassword,
	}
}

// AutoRegister 生成唯一账号与随机密码落 users 表,签发 token 返回(POST /api/v1/users)。
// 账号唯一约束冲突时换账号重试,最多 maxRegisterAttempts 次。
func (h *UserHandler) AutoRegister(c *gin.Context) {
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
			Success(c, http.StatusCreated, gin.H{
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

// Me 返回当前登录用户的账号与密码(GET /api/v1/users/me)。
func (h *UserHandler) Me(c *gin.Context) {
	userID, ok := middleware.GetUserID(c)
	if !ok {
		return
	}

	user, err := h.users.GetUserByID(c.Request.Context(), userID)
	if errors.Is(err, store.ErrUserNotFound) {
		Error(c, http.StatusNotFound, CodeUserNotFound, "用户不存在")
		return
	}
	if err != nil {
		internalError(c, "get user", err)
		return
	}
	Success(c, http.StatusOK, gin.H{
		"account":  user.Account,
		"password": user.Password,
	})
}
