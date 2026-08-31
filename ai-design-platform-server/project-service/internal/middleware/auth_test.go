package middleware

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
)

// testUserID 是测试用的合法 UUID 用户 id。
const testUserID = "11111111-1111-1111-1111-111111111111"

// newAuthRouter 构建挂载 Auth 中间件的测试路由器,受保护 handler 回显解析出的 user_id。
// 若请求到达 handler 而 user_id 缺失,说明中间件未正确注入。
func newAuthRouter(t *testing.T) *gin.Engine {
	t.Helper()
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.GET("/protected", Auth(), func(c *gin.Context) {
		userID, ok := GetUserID(c)
		if !ok {
			c.JSON(http.StatusInternalServerError, gin.H{"error": "user_id missing"})
			return
		}
		c.JSON(http.StatusOK, gin.H{"user_id": userID})
	})
	return r
}

func doProtected(t *testing.T, r *gin.Engine, header string) *httptest.ResponseRecorder {
	t.Helper()
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/protected", nil)
	if header != "" {
		req.Header.Set("X-User-Id", header)
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
	r := newAuthRouter(t)
	w := doProtected(t, r, "")
	assertUnauthorized(t, w, "", "missing header")
}

func TestAuthRejectsMalformedHeader(t *testing.T) {
	r := newAuthRouter(t)
	for _, header := range []string{
		"not-a-uuid",
		"12345",
		"11111111-1111-1111-1111-11111111111",   // 缺一位
		"11111111-1111-1111-1111-1111111111111", // 多一位
		"user-123",
		"11111111-1111-1111-1111-11111111111g", // 非 hex
		"Bearer abc",
	} {
		w := doProtected(t, r, header)
		assertUnauthorized(t, w, header, "malformed header")
	}
}

func TestAuthInjectsUserID(t *testing.T) {
	r := newAuthRouter(t)

	w := doProtected(t, r, testUserID)
	if w.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s, want 200", w.Code, w.Body.String())
	}
	var body struct {
		UserID string `json:"user_id"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &body); err != nil {
		t.Fatalf("unmarshal body: %v", err)
	}
	if body.UserID != testUserID {
		t.Errorf("user_id = %q, want %q", body.UserID, testUserID)
	}
}

func TestGetUserIDAbsent(t *testing.T) {
	gin.SetMode(gin.TestMode)
	c, _ := gin.CreateTestContext(httptest.NewRecorder())

	if _, ok := GetUserID(c); ok {
		t.Error("GetUserID() = _, true, want false on fresh context")
	}
}
