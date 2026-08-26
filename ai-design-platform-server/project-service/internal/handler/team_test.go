package handler

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"ai-design-platform/project-service/internal/auth"
	"ai-design-platform/project-service/internal/middleware"
	"ai-design-platform/project-service/internal/store"

	"github.com/DATA-DOG/go-sqlmock"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgconn"
)

// handlerTeamID 是 handler 测试用的固定团队 id。
const handlerTeamID = "66666666-6666-6666-6666-666666666666"

// newTeamTestEnv 创建挂载认证中间件与四条团队路由的测试路由器。
// 使用正则匹配器,避免测试与 store 包内 SQL 常量字符串强耦合。
func newTeamTestEnv(t *testing.T) (*gin.Engine, sqlmock.Sqlmock, *auth.Manager) {
	t.Helper()
	db, mock, err := sqlmock.New(sqlmock.QueryMatcherOption(sqlmock.QueryMatcherRegexp))
	if err != nil {
		t.Fatalf("sqlmock.New() error = %v", err)
	}
	t.Cleanup(func() { db.Close() })
	tokens := auth.NewManager("test-secret")

	gin.SetMode(gin.TestMode)
	r := gin.New()
	h := NewTeamHandler(store.NewTeams(db))
	teams := r.Group("/api/v1/teams", middleware.Auth(tokens))
	teams.GET("", h.List)
	teams.POST("", h.Create)
	teams.GET("/search", h.Search)
	teams.POST("/:id/join", h.Join)
	return r, mock, tokens
}

// doTeamRequest 以固定用户身份(token 签发 handlerUserID)向团队路由发起请求。
func doTeamRequest(t *testing.T, r *gin.Engine, tokens *auth.Manager, method, path, body string) *httptest.ResponseRecorder {
	t.Helper()
	token, err := tokens.Sign(handlerUserID)
	if err != nil {
		t.Fatalf("Sign() error = %v, want nil", err)
	}
	w := httptest.NewRecorder()
	var req *http.Request
	if body == "" {
		req = httptest.NewRequest(method, path, nil)
	} else {
		req = httptest.NewRequest(method, path, strings.NewReader(body))
		req.Header.Set("Content-Type", "application/json")
	}
	req.Header.Set("Authorization", "Bearer "+token)
	r.ServeHTTP(w, req)
	return w
}

// teamRow 构造 teams 表一行数据的 sqlmock Rows。
func teamRow(id, name string, description any, ownerID string) *sqlmock.Rows {
	return sqlmock.NewRows([]string{"id", "name", "description", "owner_id", "created_at"}).
		AddRow(id, name, description, ownerID, time.Now())
}

// teamResp 是与 teamJSON 结构对应的响应体(camelCase 契约)。
type teamResp struct {
	ID          string    `json:"id"`
	Name        string    `json:"name"`
	Description *string   `json:"description"`
	OwnerID     string    `json:"ownerId"`
	CreatedAt   time.Time `json:"createdAt"`
}

// TestListTeamsEmpty 覆盖空列表:响应为裸数组 [] 而非 null。
func TestListTeamsEmpty(t *testing.T) {
	r, mock, tokens := newTeamTestEnv(t)

	mock.ExpectQuery("SELECT t.id, t.name, t.description, t.owner_id, t.created_at FROM teams t JOIN team_members").
		WithArgs(handlerUserID).
		WillReturnRows(sqlmock.NewRows([]string{"id", "name", "description", "owner_id", "created_at"}))

	w := doTeamRequest(t, r, tokens, http.MethodGet, "/api/v1/teams", "")
	if w.Code != http.StatusOK {
		t.Fatalf("GET /teams status = %d, body = %s, want 200", w.Code, w.Body.String())
	}
	if got := strings.TrimSpace(w.Body.String()); got != "[]" {
		t.Errorf("GET /teams body = %s, want []", got)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

// TestListTeams 覆盖有数据列表:camelCase 字段映射与行顺序。
func TestListTeams(t *testing.T) {
	r, mock, tokens := newTeamTestEnv(t)

	mock.ExpectQuery("SELECT t.id, t.name, t.description, t.owner_id, t.created_at FROM teams t JOIN team_members").
		WithArgs(handlerUserID).
		WillReturnRows(
			teamRow(handlerTeamID, "设计组", "团队描述", handlerUserID).
				AddRow("77777777-7777-7777-7777-777777777777", "研发组", nil, handlerUserID, time.Now()),
		)

	w := doTeamRequest(t, r, tokens, http.MethodGet, "/api/v1/teams", "")
	if w.Code != http.StatusOK {
		t.Fatalf("GET /teams status = %d, body = %s, want 200", w.Code, w.Body.String())
	}
	var teams []teamResp
	if err := json.Unmarshal(w.Body.Bytes(), &teams); err != nil {
		t.Fatalf("unmarshal body: %v", err)
	}
	if len(teams) != 2 {
		t.Fatalf("teams len = %d, want 2", len(teams))
	}
	if teams[0].ID != handlerTeamID || teams[0].Name != "设计组" || teams[0].OwnerID != handlerUserID {
		t.Errorf("teams[0] = %+v, want team %s", teams[0], handlerTeamID)
	}
	if teams[0].Description == nil || *teams[0].Description != "团队描述" {
		t.Errorf("teams[0].Description = %v, want %q", teams[0].Description, "团队描述")
	}
	if teams[0].CreatedAt.IsZero() {
		t.Errorf("teams[0].CreatedAt = zero, want non-zero")
	}
	if teams[1].Description != nil {
		t.Errorf("teams[1].Description = %v, want nil (NULL 描述省略)", *teams[1].Description)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

// TestCreateTeamSuccess 覆盖创建成功:201 + camelCase 响应,创建者写入成员表。
func TestCreateTeamSuccess(t *testing.T) {
	r, mock, tokens := newTeamTestEnv(t)

	mock.ExpectBegin()
	mock.ExpectQuery("INSERT INTO teams").
		WithArgs("设计组", "团队描述", handlerUserID).
		WillReturnRows(teamRow(handlerTeamID, "设计组", "团队描述", handlerUserID))
	mock.ExpectExec("INSERT INTO team_members").
		WithArgs(handlerTeamID, handlerUserID).
		WillReturnResult(sqlmock.NewResult(1, 1))
	mock.ExpectCommit()

	w := doTeamRequest(t, r, tokens, http.MethodPost, "/api/v1/teams", `{"name":"设计组","description":"团队描述"}`)
	if w.Code != http.StatusCreated {
		t.Fatalf("POST /teams status = %d, body = %s, want 201", w.Code, w.Body.String())
	}
	var got teamResp
	if err := json.Unmarshal(w.Body.Bytes(), &got); err != nil {
		t.Fatalf("unmarshal body: %v", err)
	}
	if got.ID != handlerTeamID || got.Name != "设计组" || got.OwnerID != handlerUserID {
		t.Errorf("POST /teams body = %+v, want team %s owned by %s", got, handlerTeamID, handlerUserID)
	}
	if got.Description == nil || *got.Description != "团队描述" {
		t.Errorf("POST /teams description = %v, want %q", got.Description, "团队描述")
	}
	if got.CreatedAt.IsZero() {
		t.Errorf("POST /teams createdAt = zero, want non-zero")
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

// TestCreateTeamWithoutDescription 覆盖描述缺省:参数落 NULL,响应省略 description 字段。
func TestCreateTeamWithoutDescription(t *testing.T) {
	r, mock, tokens := newTeamTestEnv(t)

	mock.ExpectBegin()
	mock.ExpectQuery("INSERT INTO teams").
		WithArgs("设计组", nil, handlerUserID).
		WillReturnRows(teamRow(handlerTeamID, "设计组", nil, handlerUserID))
	mock.ExpectExec("INSERT INTO team_members").
		WithArgs(handlerTeamID, handlerUserID).
		WillReturnResult(sqlmock.NewResult(1, 1))
	mock.ExpectCommit()

	w := doTeamRequest(t, r, tokens, http.MethodPost, "/api/v1/teams", `{"name":"设计组"}`)
	if w.Code != http.StatusCreated {
		t.Fatalf("POST /teams status = %d, body = %s, want 201", w.Code, w.Body.String())
	}
	if strings.Contains(w.Body.String(), "description") {
		t.Errorf("POST /teams body = %s, want description omitted", w.Body.String())
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

// TestCreateTeamMissingName 覆盖名称必填:空串/纯空白/缺字段均 400,不触碰数据库。
func TestCreateTeamMissingName(t *testing.T) {
	for _, body := range []string{`{"name":""}`, `{"name":"   "}`, `{}`} {
		t.Run(body, func(t *testing.T) {
			r, mock, tokens := newTeamTestEnv(t)

			w := doTeamRequest(t, r, tokens, http.MethodPost, "/api/v1/teams", body)
			if w.Code != http.StatusBadRequest {
				t.Fatalf("POST /teams %s status = %d, body = %s, want 400", body, w.Code, w.Body.String())
			}
			var resp struct {
				Error string `json:"error"`
			}
			if err := json.Unmarshal(w.Body.Bytes(), &resp); err != nil || resp.Error == "" {
				t.Errorf("POST /teams %s error field = %q, want non-empty", body, resp.Error)
			}
			// 名称校验失败不应发起任何数据库调用。
			if err := mock.ExpectationsWereMet(); err != nil {
				t.Errorf("unmet expectations: %v", err)
			}
		})
	}
}

// TestCreateTeamInvalidBody 覆盖请求体非法 JSON。
func TestCreateTeamInvalidBody(t *testing.T) {
	r, mock, tokens := newTeamTestEnv(t)

	w := doTeamRequest(t, r, tokens, http.MethodPost, "/api/v1/teams", `not-json`)
	if w.Code != http.StatusBadRequest {
		t.Fatalf("POST /teams status = %d, body = %s, want 400", w.Code, w.Body.String())
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

// TestCreateTeamMemberInsertFails 覆盖成员写入失败:返回 500(事务回滚在 store 层测试覆盖)。
func TestCreateTeamMemberInsertFails(t *testing.T) {
	r, mock, tokens := newTeamTestEnv(t)

	mock.ExpectBegin()
	mock.ExpectQuery("INSERT INTO teams").
		WithArgs("设计组", nil, handlerUserID).
		WillReturnRows(teamRow(handlerTeamID, "设计组", nil, handlerUserID))
	mock.ExpectExec("INSERT INTO team_members").
		WithArgs(handlerTeamID, handlerUserID).
		WillReturnError(&pgconn.PgError{Code: "23505"})
	mock.ExpectRollback()

	w := doTeamRequest(t, r, tokens, http.MethodPost, "/api/v1/teams", `{"name":"设计组"}`)
	if w.Code != http.StatusInternalServerError {
		t.Fatalf("POST /teams status = %d, body = %s, want 500", w.Code, w.Body.String())
	}
	var resp struct {
		Error string `json:"error"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &resp); err != nil || resp.Error == "" {
		t.Errorf("POST /teams error field = %q, want non-empty", resp.Error)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

// TestSearchTeams 覆盖按名称模糊匹配:ILIKE 模式与用户参数正确传递。
func TestSearchTeams(t *testing.T) {
	r, mock, tokens := newTeamTestEnv(t)

	mock.ExpectQuery("ILIKE").
		WithArgs("%设计%", handlerUserID).
		WillReturnRows(teamRow(handlerTeamID, "设计组", nil, handlerUserID))

	w := doTeamRequest(t, r, tokens, http.MethodGet, "/api/v1/teams/search?keyword=设计", "")
	if w.Code != http.StatusOK {
		t.Fatalf("GET /teams/search status = %d, body = %s, want 200", w.Code, w.Body.String())
	}
	var teams []teamResp
	if err := json.Unmarshal(w.Body.Bytes(), &teams); err != nil {
		t.Fatalf("unmarshal body: %v", err)
	}
	if len(teams) != 1 || teams[0].ID != handlerTeamID || teams[0].Name != "设计组" {
		t.Errorf("GET /teams/search body = %+v, want team %s", teams, handlerTeamID)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

// TestSearchTeamsExcludesJoined 覆盖排除已加入团队:SQL 含 NOT EXISTS 且以当前用户过滤。
func TestSearchTeamsExcludesJoined(t *testing.T) {
	r, mock, tokens := newTeamTestEnv(t)

	mock.ExpectQuery("NOT EXISTS").
		WithArgs("%设计%", handlerUserID).
		WillReturnRows(sqlmock.NewRows([]string{"id", "name", "description", "owner_id", "created_at"}))

	w := doTeamRequest(t, r, tokens, http.MethodGet, "/api/v1/teams/search?keyword=设计", "")
	if w.Code != http.StatusOK {
		t.Fatalf("GET /teams/search status = %d, body = %s, want 200", w.Code, w.Body.String())
	}
	if got := strings.TrimSpace(w.Body.String()); got != "[]" {
		t.Errorf("GET /teams/search body = %s, want []", got)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

// TestSearchTeamsEmptyKeyword 覆盖空关键字:缺失或纯空白均 400,不触碰数据库。
func TestSearchTeamsEmptyKeyword(t *testing.T) {
	for _, path := range []string{"/api/v1/teams/search", "/api/v1/teams/search?keyword=", "/api/v1/teams/search?keyword=%20%20"} {
		t.Run(path, func(t *testing.T) {
			r, mock, tokens := newTeamTestEnv(t)

			w := doTeamRequest(t, r, tokens, http.MethodGet, path, "")
			if w.Code != http.StatusBadRequest {
				t.Fatalf("GET %s status = %d, body = %s, want 400", path, w.Code, w.Body.String())
			}
			var resp struct {
				Error string `json:"error"`
			}
			if err := json.Unmarshal(w.Body.Bytes(), &resp); err != nil || resp.Error == "" {
				t.Errorf("GET %s error field = %q, want non-empty", path, resp.Error)
			}
			if err := mock.ExpectationsWereMet(); err != nil {
				t.Errorf("unmet expectations: %v", err)
			}
		})
	}
}

// TestJoinTeamSuccess 覆盖加入成功:200 + success 标记。
func TestJoinTeamSuccess(t *testing.T) {
	r, mock, tokens := newTeamTestEnv(t)

	mock.ExpectExec("INSERT INTO team_members.*SELECT t.id").
		WithArgs(handlerTeamID, handlerUserID).
		WillReturnResult(sqlmock.NewResult(0, 1))

	w := doTeamRequest(t, r, tokens, http.MethodPost, "/api/v1/teams/"+handlerTeamID+"/join", "")
	if w.Code != http.StatusOK {
		t.Fatalf("POST /teams/:id/join status = %d, body = %s, want 200", w.Code, w.Body.String())
	}
	var resp struct {
		Success bool `json:"success"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &resp); err != nil || !resp.Success {
		t.Errorf("POST /teams/:id/join body = %s, want success true", w.Body.String())
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

// TestJoinTeamConflict 覆盖重复加入:唯一约束冲突映射为 409。
func TestJoinTeamConflict(t *testing.T) {
	r, mock, tokens := newTeamTestEnv(t)

	mock.ExpectExec("INSERT INTO team_members.*SELECT t.id").
		WithArgs(handlerTeamID, handlerUserID).
		WillReturnError(&pgconn.PgError{Code: "23505", Message: "duplicate key value violates unique constraint"})

	w := doTeamRequest(t, r, tokens, http.MethodPost, "/api/v1/teams/"+handlerTeamID+"/join", "")
	if w.Code != http.StatusConflict {
		t.Fatalf("POST /teams/:id/join status = %d, body = %s, want 409", w.Code, w.Body.String())
	}
	var resp struct {
		Error string `json:"error"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &resp); err != nil || resp.Error == "" {
		t.Errorf("POST /teams/:id/join error field = %q, want non-empty", resp.Error)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

// TestJoinTeamNotFound 覆盖团队不存在:0 行受影响映射为 404。
func TestJoinTeamNotFound(t *testing.T) {
	r, mock, tokens := newTeamTestEnv(t)

	mock.ExpectExec("INSERT INTO team_members.*SELECT t.id").
		WithArgs(handlerTeamID, handlerUserID).
		WillReturnResult(sqlmock.NewResult(0, 0))

	w := doTeamRequest(t, r, tokens, http.MethodPost, "/api/v1/teams/"+handlerTeamID+"/join", "")
	if w.Code != http.StatusNotFound {
		t.Fatalf("POST /teams/:id/join status = %d, body = %s, want 404", w.Code, w.Body.String())
	}
	var resp struct {
		Error string `json:"error"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &resp); err != nil || resp.Error == "" {
		t.Errorf("POST /teams/:id/join error field = %q, want non-empty", resp.Error)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

// TestJoinTeamInvalidID 覆盖 P3 修复:非 UUID 的 :id 返回 400 而非 500,不触碰数据库。
func TestJoinTeamInvalidID(t *testing.T) {
	r, mock, tokens := newTeamTestEnv(t)

	w := doTeamRequest(t, r, tokens, http.MethodPost, "/api/v1/teams/not-a-uuid/join", "")
	if w.Code != http.StatusBadRequest {
		t.Fatalf("POST /teams/:id/join status = %d, body = %s, want 400", w.Code, w.Body.String())
	}
	var resp struct {
		Error string `json:"error"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &resp); err != nil || resp.Error == "" {
		t.Errorf("POST /teams/:id/join error field = %q, want non-empty", resp.Error)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}
