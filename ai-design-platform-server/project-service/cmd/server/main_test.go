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

// respEnvelope 是统一响应信封,Data 保持原始 JSON 以便二次解析业务数据。
type respEnvelope struct {
	Code int             `json:"code"`
	Msg  string          `json:"msg"`
	Data json.RawMessage `json:"data"`
}

// unmarshalEnvelope 解析统一信封并断言成功字段(code=0、msg=success)。
func unmarshalEnvelope(t *testing.T, body []byte) respEnvelope {
	t.Helper()
	var env respEnvelope
	if err := json.Unmarshal(body, &env); err != nil {
		t.Fatalf("unmarshal envelope: %v", err)
	}
	if env.Code != 0 {
		t.Errorf("envelope code = %d, want 0 (success), body = %s", env.Code, body)
	}
	if env.Msg != "success" {
		t.Errorf("envelope msg = %q, want %q", env.Msg, "success")
	}
	return env
}

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
		{http.MethodGet, "/api/v1/users/me"},
		{http.MethodGet, "/api/v1/users/me/teams"},
		{http.MethodGet, "/api/v1/users/me/projects"},
		{http.MethodGet, "/api/v1/teams"},
		{http.MethodPost, "/api/v1/teams"},
		// :id 用合法 UUID 形式,与非 UUID 400 用例(TestUserDomainRoutesRejectNonUUID)区分。
		{http.MethodPost, "/api/v1/teams/44444444-4444-4444-4444-444444444444/members"},
		{http.MethodGet, "/api/v1/teams/44444444-4444-4444-4444-444444444444/projects"},
		{http.MethodPost, "/api/v1/projects"},
		{http.MethodGet, "/api/v1/projects/44444444-4444-4444-4444-444444444444"},
	}
	for _, req := range requests {
		w := doRequest(r, req[0], req[1], "")
		if w.Code != http.StatusUnauthorized {
			t.Errorf("%s %s without token status = %d, want 401", req[0], req[1], w.Code)
			continue
		}
		var env respEnvelope
		if err := json.Unmarshal(w.Body.Bytes(), &env); err != nil {
			t.Fatalf("%s %s unmarshal envelope: %v", req[0], req[1], err)
		}
		if env.Code != 40100 || env.Msg != "未认证" {
			t.Errorf("%s %s envelope = {code:%d msg:%q}, want {code:40100 msg:%q}", req[0], req[1], env.Code, env.Msg, "未认证")
		}
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

// TestPersonalProjectsRoutesWired 验证 /users/me/projects 路由已挂真实 handler 而非 404 占位:
// 带有效 token 请求个人项目列表应返回 200 信封,data 为裸数组 []。
func TestPersonalProjectsRoutesWired(t *testing.T) {
	r, mock, tokens := newTestRouter(t)
	token, err := tokens.Sign("user-123")
	if err != nil {
		t.Fatalf("Sign() error = %v, want nil", err)
	}

	mock.ExpectQuery("SELECT id, name, description, level, team_id, created_by, created_at FROM projects WHERE team_id IS NULL").
		WithArgs("user-123").
		WillReturnRows(sqlmock.NewRows([]string{"id", "name", "description", "level", "team_id", "created_by", "created_at"}))

	w := doRequest(r, http.MethodGet, "/api/v1/users/me/projects", token)
	if w.Code != http.StatusOK {
		t.Fatalf("GET /api/v1/users/me/projects with valid token status = %d, body = %s, want 200", w.Code, w.Body.String())
	}
	env := unmarshalEnvelope(t, w.Body.Bytes())
	if got := strings.TrimSpace(string(env.Data)); got != "[]" {
		t.Errorf("GET /api/v1/users/me/projects data = %s, want []", got)
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
		{http.MethodPost, "/api/v1/teams/1/members"},
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

// TestTeamsSearchRoutesWired 验证 /teams 路由已挂真实 handler 而非 404 占位:
// 带有效 token 请求可加入团队列表(无 keyword)应返回 200 信封,data 为裸数组 [],并按排除已加入过滤。
func TestTeamsSearchRoutesWired(t *testing.T) {
	r, mock, tokens := newTestRouter(t)
	token, err := tokens.Sign("user-123")
	if err != nil {
		t.Fatalf("Sign() error = %v, want nil", err)
	}

	mock.ExpectQuery("ILIKE").
		WithArgs("%%", "user-123").
		WillReturnRows(sqlmock.NewRows([]string{"id", "name", "description", "owner_id", "created_at"}))

	w := doRequest(r, http.MethodGet, "/api/v1/teams", token)
	if w.Code != http.StatusOK {
		t.Fatalf("GET /api/v1/teams with valid token status = %d, body = %s, want 200", w.Code, w.Body.String())
	}
	env := unmarshalEnvelope(t, w.Body.Bytes())
	if got := strings.TrimSpace(string(env.Data)); got != "[]" {
		t.Errorf("GET /api/v1/teams data = %s, want []", got)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

// TestAutoRegisterPublic 验证 POST /users 是公开路由:不带 token 也能注册成功(201),
// 与组内其余需认证的 /users 子路由(见 TestUserDomainRoutesRequireAuth)区分。
func TestAutoRegisterPublic(t *testing.T) {
	r, mock, _ := newTestRouter(t)

	mock.ExpectQuery("INSERT INTO users").
		WithArgs(sqlmock.AnyArg(), sqlmock.AnyArg()).
		WillReturnRows(sqlmock.NewRows([]string{"id", "account", "password", "created_at"}).
			AddRow("33333333-3333-3333-3333-333333333333", "user_public", "Passw0rd12345", time.Now()))

	w := doRequest(r, http.MethodPost, "/api/v1/users", "")
	if w.Code != http.StatusCreated {
		t.Fatalf("POST /users without token status = %d, body = %s, want 201 (public)", w.Code, w.Body.String())
	}
	unmarshalEnvelope(t, w.Body.Bytes())
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

	w := doRequest(r, http.MethodPost, "/api/v1/users", "")
	if w.Code != http.StatusCreated {
		t.Fatalf("POST /users status = %d, body = %s, want 201", w.Code, w.Body.String())
	}
	env := unmarshalEnvelope(t, w.Body.Bytes())
	var reg struct {
		Account  string `json:"account"`
		Password string `json:"password"`
		Token    string `json:"token"`
	}
	if err := json.Unmarshal(env.Data, &reg); err != nil {
		t.Fatalf("unmarshal data: %v", err)
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

	w2 := doRequest(r, http.MethodGet, "/api/v1/users/me", reg.Token)
	if w2.Code != http.StatusOK {
		t.Fatalf("GET /users/me status = %d, body = %s, want 200", w2.Code, w2.Body.String())
	}
	env2 := unmarshalEnvelope(t, w2.Body.Bytes())
	var me struct {
		Account  string `json:"account"`
		Password string `json:"password"`
	}
	if err := json.Unmarshal(env2.Data, &me); err != nil {
		t.Fatalf("unmarshal data: %v", err)
	}
	if me.Account != "user_registered" || me.Password != "Passw0rd12345" {
		t.Errorf("me = (%q, %q), want (%q, %q)", me.Account, me.Password, "user_registered", "Passw0rd12345")
	}

	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}
