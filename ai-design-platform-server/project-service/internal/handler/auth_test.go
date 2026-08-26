package handler

import (
	"database/sql"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"ai-design-platform/project-service/internal/auth"
	"ai-design-platform/project-service/internal/middleware"
	"ai-design-platform/project-service/internal/store"

	"github.com/DATA-DOG/go-sqlmock"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgconn"
)

// handlerUserID 是 handler 测试用的固定用户 id。
const handlerUserID = "22222222-2222-2222-2222-222222222222"

// testPassword 是 handler 测试用的固定密码。
const testPassword = "Passw0rdAbc12345"

// newAuthTestEnv 创建带 sqlmock 的 AuthHandler 与配套 token Manager。
// 使用正则匹配器,避免测试与 store 包内 SQL 常量字符串强耦合。
func newAuthTestEnv(t *testing.T) (*AuthHandler, sqlmock.Sqlmock, *auth.Manager) {
	t.Helper()
	db, mock, err := sqlmock.New(sqlmock.QueryMatcherOption(sqlmock.QueryMatcherRegexp))
	if err != nil {
		t.Fatalf("sqlmock.New() error = %v", err)
	}
	t.Cleanup(func() { db.Close() })
	tokens := auth.NewManager("test-secret")
	return NewAuthHandler(store.NewUsers(db), tokens), mock, tokens
}

// newFixedGenerators 注入按序返回指定账号的生成器(密码固定)。
func newFixedGenerators(accounts ...string) (func() (string, error), func() (string, error), func() int) {
	next := 0
	genAccount := func() (string, error) {
		if next >= len(accounts) {
			return "", errors.New("unexpected extra account generation")
		}
		a := accounts[next]
		next++
		return a, nil
	}
	genPassword := func() (string, error) { return testPassword, nil }
	return genAccount, genPassword, func() int { return next }
}

func doAutoRegister(t *testing.T, h *AuthHandler) *httptest.ResponseRecorder {
	t.Helper()
	gin.SetMode(gin.TestMode)
	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/auth/auto-register", nil)
	h.AutoRegister(c)
	return w
}

func userRow(id, account, password string) *sqlmock.Rows {
	return sqlmock.NewRows([]string{"id", "account", "password", "created_at"}).
		AddRow(id, account, password, time.Now())
}

func TestAutoRegisterSuccess(t *testing.T) {
	h, mock, tokens := newAuthTestEnv(t)
	h.genAccount, h.genPassword, _ = newFixedGenerators("user_abc123456")

	mock.ExpectQuery("INSERT INTO users").
		WithArgs("user_abc123456", testPassword).
		WillReturnRows(userRow(handlerUserID, "user_abc123456", testPassword))

	w := doAutoRegister(t, h)
	if w.Code != http.StatusOK {
		t.Fatalf("AutoRegister() status = %d, body = %s, want 200", w.Code, w.Body.String())
	}

	var body struct {
		Account  string `json:"account"`
		Password string `json:"password"`
		Token    string `json:"token"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &body); err != nil {
		t.Fatalf("unmarshal body: %v", err)
	}
	if body.Account != "user_abc123456" {
		t.Errorf("account = %q, want %q", body.Account, "user_abc123456")
	}
	if body.Password != testPassword {
		t.Errorf("password = %q, want %q", body.Password, testPassword)
	}
	// token 应可被同一 Manager 校验,且 user_id 为落库返回的 id。
	userID, err := tokens.Verify(body.Token)
	if err != nil {
		t.Fatalf("Verify(token) error = %v, want nil", err)
	}
	if userID != handlerUserID {
		t.Errorf("token user_id = %q, want %q", userID, handlerUserID)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

func TestAutoRegisterRetriesOnConflict(t *testing.T) {
	h, mock, _ := newAuthTestEnv(t)
	genAccount, genPassword, calls := newFixedGenerators("user_a", "user_b", "user_c")
	h.genAccount, h.genPassword = genAccount, genPassword

	// 第一次账号冲突,换账号后第二次成功。
	mock.ExpectQuery("INSERT INTO users").
		WithArgs("user_a", testPassword).
		WillReturnError(&pgconn.PgError{Code: "23505"})
	mock.ExpectQuery("INSERT INTO users").
		WithArgs("user_b", testPassword).
		WillReturnRows(userRow(handlerUserID, "user_b", testPassword))

	w := doAutoRegister(t, h)
	if w.Code != http.StatusOK {
		t.Fatalf("AutoRegister() status = %d, body = %s, want 200", w.Code, w.Body.String())
	}
	var body struct {
		Account string `json:"account"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &body); err != nil {
		t.Fatalf("unmarshal body: %v", err)
	}
	if body.Account != "user_b" {
		t.Errorf("account = %q, want %q (conflict 后应换账号重试)", body.Account, "user_b")
	}
	if n := calls(); n != 2 {
		t.Errorf("genAccount calls = %d, want 2", n)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

func TestAutoRegisterConflictExhausted(t *testing.T) {
	h, mock, _ := newAuthTestEnv(t)
	h.genAccount, h.genPassword, _ = newFixedGenerators("user_a", "user_b", "user_c")

	for _, account := range []string{"user_a", "user_b", "user_c"} {
		mock.ExpectQuery("INSERT INTO users").
			WithArgs(account, testPassword).
			WillReturnError(&pgconn.PgError{Code: "23505"})
	}

	w := doAutoRegister(t, h)
	if w.Code != http.StatusInternalServerError {
		t.Fatalf("AutoRegister() status = %d, want 500", w.Code)
	}
	var body struct {
		Error string `json:"error"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &body); err != nil {
		t.Fatalf("unmarshal body: %v", err)
	}
	if body.Error == "" {
		t.Errorf("error field = %q, want non-empty", body.Error)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

func TestAutoRegisterCreateError(t *testing.T) {
	h, mock, _ := newAuthTestEnv(t)
	h.genAccount, h.genPassword, _ = newFixedGenerators("user_a")

	mock.ExpectQuery("INSERT INTO users").
		WithArgs("user_a", testPassword).
		WillReturnError(errors.New("connection refused"))

	w := doAutoRegister(t, h)
	if w.Code != http.StatusInternalServerError {
		t.Fatalf("AutoRegister() status = %d, want 500", w.Code)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

func TestAutoRegisterAccountGenError(t *testing.T) {
	h, mock, _ := newAuthTestEnv(t)
	h.genAccount = func() (string, error) { return "", errors.New("entropy exhausted") }

	w := doAutoRegister(t, h)
	if w.Code != http.StatusInternalServerError {
		t.Fatalf("AutoRegister() status = %d, want 500", w.Code)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

// newMeRouter 构建挂载认证中间件的 /auth/me 路由,验证中间件与 handler 的协作。
func newMeRouter(t *testing.T, h *AuthHandler, tokens *auth.Manager) *gin.Engine {
	t.Helper()
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.GET("/api/v1/auth/me", middleware.Auth(tokens), h.Me)
	return r
}

func doMe(t *testing.T, r *gin.Engine, bearer string) *httptest.ResponseRecorder {
	t.Helper()
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/auth/me", nil)
	if bearer != "" {
		req.Header.Set("Authorization", "Bearer "+bearer)
	}
	r.ServeHTTP(w, req)
	return w
}

func TestMeSuccess(t *testing.T) {
	h, mock, tokens := newAuthTestEnv(t)
	mock.ExpectQuery("SELECT id, account, password, created_at FROM users WHERE id").
		WithArgs(handlerUserID).
		WillReturnRows(userRow(handlerUserID, "user_me", testPassword))

	token, err := tokens.Sign(handlerUserID)
	if err != nil {
		t.Fatalf("Sign() error = %v, want nil", err)
	}

	w := doMe(t, newMeRouter(t, h, tokens), token)
	if w.Code != http.StatusOK {
		t.Fatalf("Me() status = %d, body = %s, want 200", w.Code, w.Body.String())
	}
	var body struct {
		Account  string `json:"account"`
		Password string `json:"password"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &body); err != nil {
		t.Fatalf("unmarshal body: %v", err)
	}
	if body.Account != "user_me" || body.Password != testPassword {
		t.Errorf("Me() = (%q, %q), want (%q, %q)", body.Account, body.Password, "user_me", testPassword)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

func TestMeUserNotFound(t *testing.T) {
	h, mock, tokens := newAuthTestEnv(t)
	mock.ExpectQuery("SELECT id, account, password, created_at FROM users WHERE id").
		WithArgs(handlerUserID).
		WillReturnError(sql.ErrNoRows)

	token, err := tokens.Sign(handlerUserID)
	if err != nil {
		t.Fatalf("Sign() error = %v, want nil", err)
	}

	w := doMe(t, newMeRouter(t, h, tokens), token)
	if w.Code != http.StatusNotFound {
		t.Fatalf("Me() status = %d, body = %s, want 404", w.Code, w.Body.String())
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

func TestMeRequiresAuth(t *testing.T) {
	h, mock, tokens := newAuthTestEnv(t)

	w := doMe(t, newMeRouter(t, h, tokens), "")
	if w.Code != http.StatusUnauthorized {
		t.Fatalf("Me() without token status = %d, want 401", w.Code)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}
