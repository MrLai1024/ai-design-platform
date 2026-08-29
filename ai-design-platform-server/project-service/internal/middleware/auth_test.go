package middleware

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"ai-design-platform/project-service/internal/auth"

	"github.com/gin-gonic/gin"
)

// newAuthRouter 构建挂载 Auth 中间件的测试路由器,受保护 handler 回显解析出的 user_id。
// 若请求到达 handler 而 user_id 缺失,说明中间件未正确注入。
func newAuthRouter(t *testing.T, secret string) (*gin.Engine, *auth.Manager) {
	t.Helper()
	gin.SetMode(gin.TestMode)
	m := auth.NewManager(secret)
	r := gin.New()
	r.GET("/protected", Auth(m), func(c *gin.Context) {
		userID, ok := GetUserID(c)
		if !ok {
			c.JSON(http.StatusInternalServerError, gin.H{"error": "user_id missing"})
			return
		}
		c.JSON(http.StatusOK, gin.H{"user_id": userID})
	})
	return r, m
}

func doProtected(t *testing.T, r *gin.Engine, header string) *httptest.ResponseRecorder {
	t.Helper()
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/protected", nil)
	if header != "" {
		req.Header.Set("Authorization", header)
	}
	r.ServeHTTP(w, req)
	return w
}

func assertUnauthorized(t *testing.T, w *httptest.ResponseRecorder, header, msg string) {
	t.Helper()
	if w.Code != http.StatusUnauthorized {
		t.Fatalf("%s: status = %d, body = %s, want 401", msg, w.Code, w.Body.String())
	}
	// 401 响应为统一信封:code=40100(未认证)、msg 中文、data 为 null。
	var body struct {
		Code int    `json:"code"`
		Msg  string `json:"msg"`
		Data any    `json:"data"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &body); err != nil {
		t.Fatalf("%s: unmarshal body: %v", msg, err)
	}
	if body.Code != 40100 {
		t.Errorf("%s: code = %d, want 40100", msg, body.Code)
	}
	if body.Msg != "未认证" {
		t.Errorf("%s: msg = %q, want %q", msg, body.Msg, "未认证")
	}
	if body.Data != nil {
		t.Errorf("%s: data = %v, want null", msg, body.Data)
	}
}

func TestAuthRejectsMissingHeader(t *testing.T) {
	r, _ := newAuthRouter(t, "test-secret")
	w := doProtected(t, r, "")
	assertUnauthorized(t, w, "", "missing header")
}

func TestAuthRejectsMalformedHeader(t *testing.T) {
	r, _ := newAuthRouter(t, "test-secret")
	for _, header := range []string{"Token abc", "Bearer", "Bearer ", "bearer abc.def.ghi"} {
		w := doProtected(t, r, header)
		assertUnauthorized(t, w, header, "malformed header")
	}
}

func TestAuthRejectsInvalidToken(t *testing.T) {
	r, _ := newAuthRouter(t, "test-secret")
	w := doProtected(t, r, "Bearer not.a.jwt")
	assertUnauthorized(t, w, "Bearer not.a.jwt", "invalid token")
}

func TestAuthRejectsWrongSecret(t *testing.T) {
	r, _ := newAuthRouter(t, "test-secret")
	other := auth.NewManager("other-secret")
	token, err := other.Sign("user-123")
	if err != nil {
		t.Fatalf("Sign() error = %v, want nil", err)
	}
	w := doProtected(t, r, "Bearer "+token)
	assertUnauthorized(t, w, "wrong-secret token", "token signed with other secret")
}

func TestAuthInjectsUserID(t *testing.T) {
	r, m := newAuthRouter(t, "test-secret")
	token, err := m.Sign("user-123")
	if err != nil {
		t.Fatalf("Sign() error = %v, want nil", err)
	}

	w := doProtected(t, r, "Bearer "+token)
	if w.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s, want 200", w.Code, w.Body.String())
	}
	var body struct {
		UserID string `json:"user_id"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &body); err != nil {
		t.Fatalf("unmarshal body: %v", err)
	}
	if body.UserID != "user-123" {
		t.Errorf("user_id = %q, want %q", body.UserID, "user-123")
	}
}

func TestGetUserIDAbsent(t *testing.T) {
	gin.SetMode(gin.TestMode)
	c, _ := gin.CreateTestContext(httptest.NewRecorder())

	if _, ok := GetUserID(c); ok {
		t.Error("GetUserID() = _, true, want false on fresh context")
	}
}
