package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"ai-design-platform/project-service/internal/auth"
	"ai-design-platform/project-service/internal/config"

	"github.com/DATA-DOG/go-sqlmock"
	"github.com/gin-gonic/gin"
)

// newTestRouter 创建 sqlmock 支撑的测试路由器与同密钥的 token Manager。
// 使用正则匹配器,测试不依赖 store 包内 SQL 常量字符串。
func newTestRouter(t *testing.T) (*gin.Engine, sqlmock.Sqlmock, *auth.Manager) {
	t.Helper()
	db, mock, err := sqlmock.New(sqlmock.QueryMatcherOption(sqlmock.QueryMatcherRegexp))
	if err != nil {
		t.Fatalf("sqlmock.New() error = %v", err)
	}
	t.Cleanup(func() { db.Close() })
	cfg := &config.Config{JWTSecret: "test-secret"}
	return newRouter(cfg, db), mock, auth.NewManager("test-secret")
}

func doRequest(r *gin.Engine, method, path, bearer string) *httptest.ResponseRecorder {
	w := httptest.NewRecorder()
	req := httptest.NewRequest(method, path, nil)
	if bearer != "" {
		req.Header.Set("Authorization", "Bearer "+bearer)
	}
	r.ServeHTTP(w, req)
	return w
}

func TestHealthExemptFromAuth(t *testing.T) {
	r, mock, _ := newTestRouter(t)

	w := doRequest(r, http.MethodGet, "/health", "")
	if w.Code != http.StatusOK {
		t.Fatalf("GET /health status = %d, body = %s, want 200", w.Code, w.Body.String())
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

func TestUserDomainRoutesRequireAuth(t *testing.T) {
	r, mock, _ := newTestRouter(t)

	requests := [][2]string{
		{http.MethodGet, "/api/v1/auth/me"},
		{http.MethodGet, "/api/v1/teams"},
		{http.MethodPost, "/api/v1/teams"},
		{http.MethodGet, "/api/v1/teams/search"},
		{http.MethodPost, "/api/v1/teams/1/join"},
		// id 用合法 UUID 形式,与非 UUID 400 用例(TestUserDomainRoutesRejectNonUUID)区分。
		{http.MethodGet, "/api/v1/teams/44444444-4444-4444-4444-444444444444/projects"},
		{http.MethodGet, "/api/v1/projects"},
		{http.MethodPost, "/api/v1/projects"},
		{http.MethodGet, "/api/v1/projects/1"},
	}
	for _, req := range requests {
		w := doRequest(r, req[0], req[1], "")
		if w.Code != http.StatusUnauthorized {
			t.Errorf("%s %s without token status = %d, want 401", req[0], req[1], w.Code)
			continue
		}
		var body struct {
			Error string `json:"error"`
		}
		if err := json.Unmarshal(w.Body.Bytes(), &body); err != nil || body.Error == "" {
			t.Errorf("%s %s body error field = %q, want non-empty", req[0], req[1], body.Error)
		}
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

// TestProjectsRoutesWired 验证 projects 路由已挂真实 handler 而非 404 占位:
// 带有效 token 请求个人项目列表应返回 200 裸数组。
func TestProjectsRoutesWired(t *testing.T) {
	r, mock, tokens := newTestRouter(t)
	token, err := tokens.Sign("user-123")
	if err != nil {
		t.Fatalf("Sign() error = %v, want nil", err)
	}

	mock.ExpectQuery("SELECT id, name, description, level, team_id, created_by, created_at FROM projects WHERE team_id IS NULL").
		WithArgs("user-123").
		WillReturnRows(sqlmock.NewRows([]string{"id", "name", "description", "level", "team_id", "created_by", "created_at"}))

	w := doRequest(r, http.MethodGet, "/api/v1/projects", token)
	if w.Code != http.StatusOK {
		t.Fatalf("GET /api/v1/projects with valid token status = %d, body = %s, want 200", w.Code, w.Body.String())
	}
	if got := strings.TrimSpace(w.Body.String()); got != "[]" {
		t.Errorf("GET /api/v1/projects body = %s, want []", got)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

// TestUserDomainRoutesRejectNonUUID 覆盖 P3 修复:非 UUID 路径参数返回 400 而非 500。
func TestUserDomainRoutesRejectNonUUID(t *testing.T) {
	r, mock, tokens := newTestRouter(t)
	token, err := tokens.Sign("user-123")
	if err != nil {
		t.Fatalf("Sign() error = %v, want nil", err)
	}

	requests := [][2]string{
		{http.MethodPost, "/api/v1/teams/1/join"},
		{http.MethodGet, "/api/v1/teams/1/projects"},
		{http.MethodGet, "/api/v1/projects/1"},
	}
	for _, req := range requests {
		w := doRequest(r, req[0], req[1], token)
		if w.Code != http.StatusBadRequest {
			t.Errorf("%s %s with non-UUID id status = %d, want 400", req[0], req[1], w.Code)
		}
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

// TestTeamsRoutesWired 验证 /teams 路由已挂真实 handler 而非 404 占位:
// 带有效 token 请求列表接口应返回 200 裸数组。
func TestTeamsRoutesWired(t *testing.T) {
	r, mock, tokens := newTestRouter(t)
	token, err := tokens.Sign("user-123")
	if err != nil {
		t.Fatalf("Sign() error = %v, want nil", err)
	}

	mock.ExpectQuery("SELECT t.id, t.name, t.description, t.owner_id, t.created_at FROM teams t JOIN team_members").
		WithArgs("user-123").
		WillReturnRows(sqlmock.NewRows([]string{"id", "name", "description", "owner_id", "created_at"}))

	w := doRequest(r, http.MethodGet, "/api/v1/teams", token)
	if w.Code != http.StatusOK {
		t.Fatalf("GET /api/v1/teams with valid token status = %d, body = %s, want 200", w.Code, w.Body.String())
	}
	if got := strings.TrimSpace(w.Body.String()); got != "[]" {
		t.Errorf("GET /api/v1/teams body = %s, want []", got)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

func TestAutoRegisterToMeFlow(t *testing.T) {
	r, mock, tokens := newTestRouter(t)
	userID := "33333333-3333-3333-3333-333333333333"
	now := time.Now()

	// 自动注册:落库返回完整行(账号/密码为随机生成,用 AnyArg 匹配)。
	mock.ExpectQuery("INSERT INTO users").
		WithArgs(sqlmock.AnyArg(), sqlmock.AnyArg()).
		WillReturnRows(sqlmock.NewRows([]string{"id", "account", "password", "created_at"}).
			AddRow(userID, "user_registered", "Passw0rd12345", now))

	w := doRequest(r, http.MethodPost, "/api/v1/auth/auto-register", "")
	if w.Code != http.StatusOK {
		t.Fatalf("auto-register status = %d, body = %s, want 200", w.Code, w.Body.String())
	}
	var reg struct {
		Account  string `json:"account"`
		Password string `json:"password"`
		Token    string `json:"token"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &reg); err != nil {
		t.Fatalf("unmarshal body: %v", err)
	}
	if !strings.HasPrefix(reg.Account, "user_") {
		t.Errorf("account = %q, want user_ prefix", reg.Account)
	}
	if reg.Password == "" || reg.Token == "" {
		t.Errorf("password/token = (%q, %q), want non-empty", reg.Password, reg.Token)
	}

	// 返回的 token 应可被服务端同一密钥校验,且 user_id 为落库 id。
	gotID, err := tokens.Verify(reg.Token)
	if err != nil {
		t.Fatalf("Verify(returned token) error = %v, want nil", err)
	}
	if gotID != userID {
		t.Errorf("token user_id = %q, want %q", gotID, userID)
	}

	// 用返回的 token 查询当前用户信息。
	mock.ExpectQuery("SELECT id, account, password, created_at FROM users WHERE id").
		WithArgs(userID).
		WillReturnRows(sqlmock.NewRows([]string{"id", "account", "password", "created_at"}).
			AddRow(userID, "user_registered", "Passw0rd12345", now))

	w2 := doRequest(r, http.MethodGet, "/api/v1/auth/me", reg.Token)
	if w2.Code != http.StatusOK {
		t.Fatalf("GET /auth/me status = %d, body = %s, want 200", w2.Code, w2.Body.String())
	}
	var me struct {
		Account  string `json:"account"`
		Password string `json:"password"`
	}
	if err := json.Unmarshal(w2.Body.Bytes(), &me); err != nil {
		t.Fatalf("unmarshal body: %v", err)
	}
	if me.Account != "user_registered" || me.Password != "Passw0rd12345" {
		t.Errorf("me = (%q, %q), want (%q, %q)", me.Account, me.Password, "user_registered", "Passw0rd12345")
	}

	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}
