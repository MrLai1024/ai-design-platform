package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"ai-design-platform/project-service/internal/config"

	"github.com/DATA-DOG/go-sqlmock"
	"github.com/gin-gonic/gin"
)

// testUserID 是测试用的合法 UUID 用户 id(gateway 注入的 X-User-Id 格式)。
const testUserID = "11111111-1111-1111-1111-111111111111"

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

// newTestRouter 创建 sqlmock 支撑的测试路由器。
// 使用正则匹配器,测试不依赖 store 包内 SQL 常量字符串。
func newTestRouter(t *testing.T) (*gin.Engine, sqlmock.Sqlmock) {
	t.Helper()
	db, mock, err := sqlmock.New(sqlmock.QueryMatcherOption(sqlmock.QueryMatcherRegexp))
	if err != nil {
		t.Fatalf("sqlmock.New() error = %v", err)
	}
	t.Cleanup(func() { db.Close() })
	cfg := &config.Config{}
	return newRouter(cfg, db), mock
}

// doRequest 以 xUserID(X-User-Id header 值,模拟 gateway 注入)发起请求;空串表示缺失。
func doRequest(r *gin.Engine, method, path, xUserID string) *httptest.ResponseRecorder {
	w := httptest.NewRecorder()
	req := httptest.NewRequest(method, path, nil)
	if xUserID != "" {
		req.Header.Set("X-User-Id", xUserID)
	}
	r.ServeHTTP(w, req)
	return w
}

func TestHealthExemptFromAuth(t *testing.T) {
	r, mock := newTestRouter(t)

	w := doRequest(r, http.MethodGet, "/health", "")
	if w.Code != http.StatusOK {
		t.Fatalf("GET /health status = %d, body = %s, want 200", w.Code, w.Body.String())
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

// TestUserDomainRoutesRequireAuth 验证全部业务路由在无 X-User-Id 时返回 401。
func TestUserDomainRoutesRequireAuth(t *testing.T) {
	r, mock := newTestRouter(t)

	requests := [][2]string{
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
			t.Errorf("%s %s without X-User-Id status = %d, want 401", req[0], req[1], w.Code)
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

// TestUserDomainRoutesRejectMalformedUserID 验证非法 X-User-Id(非 UUID)同样 401。
func TestUserDomainRoutesRejectMalformedUserID(t *testing.T) {
	r, mock := newTestRouter(t)

	for _, userID := range []string{"evil", "user-123", "11111111-1111-1111-1111-11111111111g"} {
		w := doRequest(r, http.MethodGet, "/api/v1/teams", userID)
		if w.Code != http.StatusUnauthorized {
			t.Errorf("GET /teams with X-User-Id=%q status = %d, want 401", userID, w.Code)
		}
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

// TestPersonalProjectsRoutesWired 验证 /users/me/projects 路由已挂真实 handler 而非 404 占位:
// 带合法 X-User-Id 请求个人项目列表应返回 200 信封,data 为裸数组 []。
func TestPersonalProjectsRoutesWired(t *testing.T) {
	r, mock := newTestRouter(t)

	mock.ExpectQuery("SELECT id, name, description, level, team_id, created_by, created_at FROM projects WHERE team_id IS NULL").
		WithArgs(testUserID).
		WillReturnRows(sqlmock.NewRows([]string{"id", "name", "description", "level", "team_id", "created_by", "created_at"}))

	w := doRequest(r, http.MethodGet, "/api/v1/users/me/projects", testUserID)
	if w.Code != http.StatusOK {
		t.Fatalf("GET /api/v1/users/me/projects with X-User-Id status = %d, body = %s, want 200", w.Code, w.Body.String())
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
	r, mock := newTestRouter(t)

	requests := [][2]string{
		{http.MethodPost, "/api/v1/teams/1/members"},
		{http.MethodGet, "/api/v1/teams/1/projects"},
		{http.MethodGet, "/api/v1/projects/1"},
	}
	for _, req := range requests {
		w := doRequest(r, req[0], req[1], testUserID)
		if w.Code != http.StatusBadRequest {
			t.Errorf("%s %s with non-UUID id status = %d, want 400", req[0], req[1], w.Code)
		}
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

// TestTeamsSearchRoutesWired 验证 /teams 路由已挂真实 handler 而非 404 占位:
// 带合法 X-User-Id 请求可加入团队列表(无 keyword)应返回 200 信封,data 为裸数组 []。
func TestTeamsSearchRoutesWired(t *testing.T) {
	r, mock := newTestRouter(t)

	mock.ExpectQuery("ILIKE").
		WithArgs("%%", testUserID).
		WillReturnRows(sqlmock.NewRows([]string{"id", "name", "description", "owner_id", "created_at"}))

	w := doRequest(r, http.MethodGet, "/api/v1/teams", testUserID)
	if w.Code != http.StatusOK {
		t.Fatalf("GET /api/v1/teams with X-User-Id status = %d, body = %s, want 200", w.Code, w.Body.String())
	}
	env := unmarshalEnvelope(t, w.Body.Bytes())
	if got := strings.TrimSpace(string(env.Data)); got != "[]" {
		t.Errorf("GET /api/v1/teams data = %s, want []", got)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}
