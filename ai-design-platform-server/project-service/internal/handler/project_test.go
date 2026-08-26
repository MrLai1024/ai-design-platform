package handler

import (
	"database/sql"
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
)

// handlerProjectID 是 handler 测试用的固定项目 id。
const handlerProjectID = "99999999-9999-9999-9999-999999999999"

// newProjectTestEnv 创建挂载认证中间件与四条项目路由的测试路由器。
// 使用正则匹配器,避免测试与 store 包内 SQL 常量字符串强耦合。
func newProjectTestEnv(t *testing.T) (*gin.Engine, sqlmock.Sqlmock, *auth.Manager) {
	t.Helper()
	db, mock, err := sqlmock.New(sqlmock.QueryMatcherOption(sqlmock.QueryMatcherRegexp))
	if err != nil {
		t.Fatalf("sqlmock.New() error = %v", err)
	}
	t.Cleanup(func() { db.Close() })
	tokens := auth.NewManager("test-secret")

	gin.SetMode(gin.TestMode)
	r := gin.New()
	h := NewProjectHandler(store.NewProjects(db))
	projects := r.Group("/api/v1/projects", middleware.Auth(tokens))
	projects.GET("", h.List)
	projects.POST("", h.Create)
	projects.GET("/:id", h.Detail)
	teams := r.Group("/api/v1/teams", middleware.Auth(tokens))
	teams.GET("/:id/projects", h.TeamProjects)
	return r, mock, tokens
}

// doProjectRequest 以固定用户身份(token 签发 handlerUserID)向项目路由发起请求。
func doProjectRequest(t *testing.T, r *gin.Engine, tokens *auth.Manager, method, path, body string) *httptest.ResponseRecorder {
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

// projectRow 构造 projects 表一行数据的 sqlmock Rows。
// teamID 传 nil 表示个人项目(库中 team_id 为 NULL)。
func projectRow(id, name string, description any, level string, teamID any, createdBy string) *sqlmock.Rows {
	return sqlmock.NewRows([]string{"id", "name", "description", "level", "team_id", "created_by", "created_at"}).
		AddRow(id, name, description, level, teamID, createdBy, time.Now())
}

// membershipRow 构造 IsMember 查询的 sqlmock Rows(member 为成员身份)。
func membershipRow(member bool) *sqlmock.Rows {
	return sqlmock.NewRows([]string{"is_member"}).AddRow(member)
}

// projectResp 是与 projectJSON 结构对应的响应体(camelCase 契约)。
type projectResp struct {
	ID          string    `json:"id"`
	Name        string    `json:"name"`
	Description *string   `json:"description"`
	Level       string    `json:"level"`
	TeamID      *string   `json:"teamId"`
	CreatedBy   string    `json:"createdBy"`
	CreatedAt   time.Time `json:"createdAt"`
}

// TestCreatePersonalProjectSuccess 覆盖创建个人项目:无 teamId 落个人项目,201 + camelCase 响应。
func TestCreatePersonalProjectSuccess(t *testing.T) {
	r, mock, tokens := newProjectTestEnv(t)

	mock.ExpectQuery("INSERT INTO projects").
		WithArgs("个人项目", "项目简介", "demo", nil, handlerUserID).
		WillReturnRows(projectRow(handlerProjectID, "个人项目", "项目简介", "demo", nil, handlerUserID))

	w := doProjectRequest(t, r, tokens, http.MethodPost, "/api/v1/projects", `{"name":"个人项目","description":"项目简介","level":"demo"}`)
	if w.Code != http.StatusCreated {
		t.Fatalf("POST /projects status = %d, body = %s, want 201", w.Code, w.Body.String())
	}
	var got projectResp
	if err := json.Unmarshal(w.Body.Bytes(), &got); err != nil {
		t.Fatalf("unmarshal body: %v", err)
	}
	if got.ID != handlerProjectID || got.Name != "个人项目" || got.Level != "demo" || got.CreatedBy != handlerUserID {
		t.Errorf("POST /projects body = %+v, want project %s created by %s", got, handlerProjectID, handlerUserID)
	}
	if got.Description == nil || *got.Description != "项目简介" {
		t.Errorf("POST /projects description = %v, want %q", got.Description, "项目简介")
	}
	if got.TeamID != nil {
		t.Errorf("POST /projects teamId = %v, want nil (无 teamId 落个人项目)", *got.TeamID)
	}
	if !strings.Contains(w.Body.String(), `"teamId":null`) {
		t.Errorf("POST /projects body = %s, want teamId 序列化为 null", w.Body.String())
	}
	if got.CreatedAt.IsZero() {
		t.Errorf("POST /projects createdAt = zero, want non-zero")
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

// TestCreatePersonalProjectWithoutDescription 覆盖简介缺省:参数落 NULL,响应省略 description 字段。
func TestCreatePersonalProjectWithoutDescription(t *testing.T) {
	r, mock, tokens := newProjectTestEnv(t)

	mock.ExpectQuery("INSERT INTO projects").
		WithArgs("个人项目", nil, "demo", nil, handlerUserID).
		WillReturnRows(projectRow(handlerProjectID, "个人项目", nil, "demo", nil, handlerUserID))

	w := doProjectRequest(t, r, tokens, http.MethodPost, "/api/v1/projects", `{"name":"个人项目","level":"demo"}`)
	if w.Code != http.StatusCreated {
		t.Fatalf("POST /projects status = %d, body = %s, want 201", w.Code, w.Body.String())
	}
	if strings.Contains(w.Body.String(), "description") {
		t.Errorf("POST /projects body = %s, want description omitted", w.Body.String())
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

// TestCreateTeamProjectSuccess 覆盖创建团队项目:先校验成员身份,再落 team_id。
func TestCreateTeamProjectSuccess(t *testing.T) {
	r, mock, tokens := newProjectTestEnv(t)

	mock.ExpectQuery("LEFT JOIN team_members").
		WithArgs(handlerTeamID, handlerUserID).
		WillReturnRows(membershipRow(true))
	mock.ExpectQuery("INSERT INTO projects").
		WithArgs("团队项目", "简介", "production", handlerTeamID, handlerUserID).
		WillReturnRows(projectRow(handlerProjectID, "团队项目", "简介", "production", handlerTeamID, handlerUserID))

	body := `{"name":"团队项目","description":"简介","level":"production","teamId":"` + handlerTeamID + `"}`
	w := doProjectRequest(t, r, tokens, http.MethodPost, "/api/v1/projects", body)
	if w.Code != http.StatusCreated {
		t.Fatalf("POST /projects status = %d, body = %s, want 201", w.Code, w.Body.String())
	}
	var got projectResp
	if err := json.Unmarshal(w.Body.Bytes(), &got); err != nil {
		t.Fatalf("unmarshal body: %v", err)
	}
	if got.TeamID == nil || *got.TeamID != handlerTeamID {
		t.Errorf("POST /projects teamId = %v, want %q", got.TeamID, handlerTeamID)
	}
	if got.Level != "production" {
		t.Errorf("POST /projects level = %q, want production", got.Level)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

// TestCreateProjectMissingName 覆盖名称必填:空串/纯空白/缺字段均 400,不触碰数据库。
func TestCreateProjectMissingName(t *testing.T) {
	for _, body := range []string{
		`{"name":"","level":"demo"}`,
		`{"name":"   ","level":"demo"}`,
		`{"level":"demo"}`,
	} {
		t.Run(body, func(t *testing.T) {
			r, mock, tokens := newProjectTestEnv(t)

			w := doProjectRequest(t, r, tokens, http.MethodPost, "/api/v1/projects", body)
			if w.Code != http.StatusBadRequest {
				t.Fatalf("POST /projects %s status = %d, body = %s, want 400", body, w.Code, w.Body.String())
			}
			var resp struct {
				Error string `json:"error"`
			}
			if err := json.Unmarshal(w.Body.Bytes(), &resp); err != nil || resp.Error == "" {
				t.Errorf("POST /projects %s error field = %q, want non-empty", body, resp.Error)
			}
			if err := mock.ExpectationsWereMet(); err != nil {
				t.Errorf("unmet expectations: %v", err)
			}
		})
	}
}

// TestCreateProjectInvalidLevel 覆盖 level 校验:缺省/空串/非法值均 400,不触碰数据库。
func TestCreateProjectInvalidLevel(t *testing.T) {
	for _, body := range []string{
		`{"name":"项目"}`,
		`{"name":"项目","level":""}`,
		`{"name":"项目","level":"staging"}`,
		`{"name":"项目","level":"DEMO"}`,
	} {
		t.Run(body, func(t *testing.T) {
			r, mock, tokens := newProjectTestEnv(t)

			w := doProjectRequest(t, r, tokens, http.MethodPost, "/api/v1/projects", body)
			if w.Code != http.StatusBadRequest {
				t.Fatalf("POST /projects %s status = %d, body = %s, want 400", body, w.Code, w.Body.String())
			}
			var resp struct {
				Error string `json:"error"`
			}
			if err := json.Unmarshal(w.Body.Bytes(), &resp); err != nil || resp.Error == "" {
				t.Errorf("POST /projects %s error field = %q, want non-empty", body, resp.Error)
			}
			if err := mock.ExpectationsWereMet(); err != nil {
				t.Errorf("unmet expectations: %v", err)
			}
		})
	}
}

// TestCreateProjectInvalidBody 覆盖请求体非法 JSON。
func TestCreateProjectInvalidBody(t *testing.T) {
	r, mock, tokens := newProjectTestEnv(t)

	w := doProjectRequest(t, r, tokens, http.MethodPost, "/api/v1/projects", `not-json`)
	if w.Code != http.StatusBadRequest {
		t.Fatalf("POST /projects status = %d, body = %s, want 400", w.Code, w.Body.String())
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

// TestCreateTeamProjectNotMember 覆盖非成员创建团队项目:403,不发起插入。
func TestCreateTeamProjectNotMember(t *testing.T) {
	r, mock, tokens := newProjectTestEnv(t)

	mock.ExpectQuery("LEFT JOIN team_members").
		WithArgs(handlerTeamID, handlerUserID).
		WillReturnRows(membershipRow(false))

	body := `{"name":"团队项目","level":"demo","teamId":"` + handlerTeamID + `"}`
	w := doProjectRequest(t, r, tokens, http.MethodPost, "/api/v1/projects", body)
	if w.Code != http.StatusForbidden {
		t.Fatalf("POST /projects status = %d, body = %s, want 403", w.Code, w.Body.String())
	}
	var resp struct {
		Error string `json:"error"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &resp); err != nil || resp.Error == "" {
		t.Errorf("POST /projects error field = %q, want non-empty", resp.Error)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

// TestCreateTeamProjectTeamNotFound 覆盖团队不存在:404,不发起插入。
func TestCreateTeamProjectTeamNotFound(t *testing.T) {
	r, mock, tokens := newProjectTestEnv(t)

	mock.ExpectQuery("LEFT JOIN team_members").
		WithArgs(handlerTeamID, handlerUserID).
		WillReturnError(sql.ErrNoRows)

	body := `{"name":"团队项目","level":"demo","teamId":"` + handlerTeamID + `"}`
	w := doProjectRequest(t, r, tokens, http.MethodPost, "/api/v1/projects", body)
	if w.Code != http.StatusNotFound {
		t.Fatalf("POST /projects status = %d, body = %s, want 404", w.Code, w.Body.String())
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

// TestCreateProjectInvalidTeamID 覆盖非 UUID 的 teamId:400,不触碰数据库。
func TestCreateProjectInvalidTeamID(t *testing.T) {
	r, mock, tokens := newProjectTestEnv(t)

	w := doProjectRequest(t, r, tokens, http.MethodPost, "/api/v1/projects", `{"name":"项目","level":"demo","teamId":"not-a-uuid"}`)
	if w.Code != http.StatusBadRequest {
		t.Fatalf("POST /projects status = %d, body = %s, want 400", w.Code, w.Body.String())
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

// TestCreateProjectInsertError 覆盖插入失败:返回 500。
func TestCreateProjectInsertError(t *testing.T) {
	r, mock, tokens := newProjectTestEnv(t)

	mock.ExpectQuery("INSERT INTO projects").
		WithArgs("个人项目", nil, "demo", nil, handlerUserID).
		WillReturnError(sql.ErrConnDone)

	w := doProjectRequest(t, r, tokens, http.MethodPost, "/api/v1/projects", `{"name":"个人项目","level":"demo"}`)
	if w.Code != http.StatusInternalServerError {
		t.Fatalf("POST /projects status = %d, body = %s, want 500", w.Code, w.Body.String())
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

// TestListPersonalProjectsEmpty 覆盖空列表:响应为裸数组 [] 而非 null。
func TestListPersonalProjectsEmpty(t *testing.T) {
	r, mock, tokens := newProjectTestEnv(t)

	mock.ExpectQuery("FROM projects WHERE team_id IS NULL").
		WithArgs(handlerUserID).
		WillReturnRows(sqlmock.NewRows([]string{"id", "name", "description", "level", "team_id", "created_by", "created_at"}))

	w := doProjectRequest(t, r, tokens, http.MethodGet, "/api/v1/projects", "")
	if w.Code != http.StatusOK {
		t.Fatalf("GET /projects status = %d, body = %s, want 200", w.Code, w.Body.String())
	}
	if got := strings.TrimSpace(w.Body.String()); got != "[]" {
		t.Errorf("GET /projects body = %s, want []", got)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

// TestListPersonalProjects 覆盖有数据列表:camelCase 字段映射与行顺序透传。
func TestListPersonalProjects(t *testing.T) {
	r, mock, tokens := newProjectTestEnv(t)

	mock.ExpectQuery("FROM projects WHERE team_id IS NULL").
		WithArgs(handlerUserID).
		WillReturnRows(
			projectRow(handlerProjectID, "个人项目", "简介", "demo", nil, handlerUserID).
				AddRow("88888888-8888-8888-8888-888888888888", "生产项目", nil, "production", nil, handlerUserID, time.Now()),
		)

	w := doProjectRequest(t, r, tokens, http.MethodGet, "/api/v1/projects", "")
	if w.Code != http.StatusOK {
		t.Fatalf("GET /projects status = %d, body = %s, want 200", w.Code, w.Body.String())
	}
	var projects []projectResp
	if err := json.Unmarshal(w.Body.Bytes(), &projects); err != nil {
		t.Fatalf("unmarshal body: %v", err)
	}
	if len(projects) != 2 {
		t.Fatalf("GET /projects len = %d, want 2", len(projects))
	}
	if projects[0].ID != handlerProjectID || projects[0].Name != "个人项目" || projects[0].Level != "demo" {
		t.Errorf("GET /projects [0] = %+v, want project %s", projects[0], handlerProjectID)
	}
	if projects[0].Description == nil || *projects[0].Description != "简介" {
		t.Errorf("GET /projects [0] description = %v, want %q", projects[0].Description, "简介")
	}
	if projects[0].TeamID != nil || projects[1].TeamID != nil {
		t.Errorf("GET /projects teamId = (%v, %v), want nil (个人项目)", projects[0].TeamID, projects[1].TeamID)
	}
	if projects[1].Description != nil {
		t.Errorf("GET /projects [1] description = %v, want nil", *projects[1].Description)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

// TestListTeamProjectsSuccess 覆盖团队项目列表:成员可见,teamId 字段透传。
func TestListTeamProjectsSuccess(t *testing.T) {
	r, mock, tokens := newProjectTestEnv(t)

	mock.ExpectQuery("LEFT JOIN team_members").
		WithArgs(handlerTeamID, handlerUserID).
		WillReturnRows(membershipRow(true))
	mock.ExpectQuery("FROM projects WHERE team_id").
		WithArgs(handlerTeamID).
		WillReturnRows(projectRow(handlerProjectID, "团队项目", nil, "demo", handlerTeamID, handlerUserID))

	w := doProjectRequest(t, r, tokens, http.MethodGet, "/api/v1/teams/"+handlerTeamID+"/projects", "")
	if w.Code != http.StatusOK {
		t.Fatalf("GET /teams/:id/projects status = %d, body = %s, want 200", w.Code, w.Body.String())
	}
	var projects []projectResp
	if err := json.Unmarshal(w.Body.Bytes(), &projects); err != nil {
		t.Fatalf("unmarshal body: %v", err)
	}
	if len(projects) != 1 {
		t.Fatalf("GET /teams/:id/projects len = %d, want 1", len(projects))
	}
	if projects[0].ID != handlerProjectID || projects[0].TeamID == nil || *projects[0].TeamID != handlerTeamID {
		t.Errorf("GET /teams/:id/projects [0] = %+v, want project %s of team %s", projects[0], handlerProjectID, handlerTeamID)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

// TestListTeamProjectsEmpty 覆盖团队项目空列表:响应为 []。
func TestListTeamProjectsEmpty(t *testing.T) {
	r, mock, tokens := newProjectTestEnv(t)

	mock.ExpectQuery("LEFT JOIN team_members").
		WithArgs(handlerTeamID, handlerUserID).
		WillReturnRows(membershipRow(true))
	mock.ExpectQuery("FROM projects WHERE team_id").
		WithArgs(handlerTeamID).
		WillReturnRows(sqlmock.NewRows([]string{"id", "name", "description", "level", "team_id", "created_by", "created_at"}))

	w := doProjectRequest(t, r, tokens, http.MethodGet, "/api/v1/teams/"+handlerTeamID+"/projects", "")
	if w.Code != http.StatusOK {
		t.Fatalf("GET /teams/:id/projects status = %d, body = %s, want 200", w.Code, w.Body.String())
	}
	if got := strings.TrimSpace(w.Body.String()); got != "[]" {
		t.Errorf("GET /teams/:id/projects body = %s, want []", got)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

// TestListTeamProjectsNotMember 覆盖非成员访问团队项目列表:403。
func TestListTeamProjectsNotMember(t *testing.T) {
	r, mock, tokens := newProjectTestEnv(t)

	mock.ExpectQuery("LEFT JOIN team_members").
		WithArgs(handlerTeamID, handlerUserID).
		WillReturnRows(membershipRow(false))

	w := doProjectRequest(t, r, tokens, http.MethodGet, "/api/v1/teams/"+handlerTeamID+"/projects", "")
	if w.Code != http.StatusForbidden {
		t.Fatalf("GET /teams/:id/projects status = %d, body = %s, want 403", w.Code, w.Body.String())
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

// TestListTeamProjectsTeamNotFound 覆盖团队不存在:404。
func TestListTeamProjectsTeamNotFound(t *testing.T) {
	r, mock, tokens := newProjectTestEnv(t)

	mock.ExpectQuery("LEFT JOIN team_members").
		WithArgs(handlerTeamID, handlerUserID).
		WillReturnError(sql.ErrNoRows)

	w := doProjectRequest(t, r, tokens, http.MethodGet, "/api/v1/teams/"+handlerTeamID+"/projects", "")
	if w.Code != http.StatusNotFound {
		t.Fatalf("GET /teams/:id/projects status = %d, body = %s, want 404", w.Code, w.Body.String())
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

// TestListTeamProjectsInvalidTeamID 覆盖 P3:非 UUID 的 :id 返回 400,不触碰数据库。
func TestListTeamProjectsInvalidTeamID(t *testing.T) {
	r, mock, tokens := newProjectTestEnv(t)

	w := doProjectRequest(t, r, tokens, http.MethodGet, "/api/v1/teams/not-a-uuid/projects", "")
	if w.Code != http.StatusBadRequest {
		t.Fatalf("GET /teams/:id/projects status = %d, body = %s, want 400", w.Code, w.Body.String())
	}
	var resp struct {
		Error string `json:"error"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &resp); err != nil || resp.Error == "" {
		t.Errorf("GET /teams/:id/projects error field = %q, want non-empty", resp.Error)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

// TestGetProjectDetailPersonal 覆盖个人项目详情:创建者可见,teamId 为 null。
func TestGetProjectDetailPersonal(t *testing.T) {
	r, mock, tokens := newProjectTestEnv(t)

	mock.ExpectQuery("FROM projects WHERE id").
		WithArgs(handlerProjectID).
		WillReturnRows(projectRow(handlerProjectID, "个人项目", "简介", "demo", nil, handlerUserID))

	w := doProjectRequest(t, r, tokens, http.MethodGet, "/api/v1/projects/"+handlerProjectID, "")
	if w.Code != http.StatusOK {
		t.Fatalf("GET /projects/:id status = %d, body = %s, want 200", w.Code, w.Body.String())
	}
	var got projectResp
	if err := json.Unmarshal(w.Body.Bytes(), &got); err != nil {
		t.Fatalf("unmarshal body: %v", err)
	}
	if got.ID != handlerProjectID || got.CreatedBy != handlerUserID || got.Level != "demo" {
		t.Errorf("GET /projects/:id body = %+v, want project %s", got, handlerProjectID)
	}
	if got.TeamID != nil {
		t.Errorf("GET /projects/:id teamId = %v, want nil", *got.TeamID)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

// TestGetProjectDetailOthersPersonalForbidden 覆盖他人个人项目:非创建者 403 不可见。
func TestGetProjectDetailOthersPersonalForbidden(t *testing.T) {
	r, mock, tokens := newProjectTestEnv(t)

	mock.ExpectQuery("FROM projects WHERE id").
		WithArgs(handlerProjectID).
		WillReturnRows(projectRow(handlerProjectID, "他人项目", nil, "demo", nil, "11111111-1111-1111-1111-111111111111"))

	w := doProjectRequest(t, r, tokens, http.MethodGet, "/api/v1/projects/"+handlerProjectID, "")
	if w.Code != http.StatusForbidden {
		t.Fatalf("GET /projects/:id status = %d, body = %s, want 403", w.Code, w.Body.String())
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

// TestGetProjectDetailTeamMember 覆盖团队项目详情:团队成员可见。
func TestGetProjectDetailTeamMember(t *testing.T) {
	r, mock, tokens := newProjectTestEnv(t)

	mock.ExpectQuery("FROM projects WHERE id").
		WithArgs(handlerProjectID).
		WillReturnRows(projectRow(handlerProjectID, "团队项目", nil, "production", handlerTeamID, "11111111-1111-1111-1111-111111111111"))
	mock.ExpectQuery("LEFT JOIN team_members").
		WithArgs(handlerTeamID, handlerUserID).
		WillReturnRows(membershipRow(true))

	w := doProjectRequest(t, r, tokens, http.MethodGet, "/api/v1/projects/"+handlerProjectID, "")
	if w.Code != http.StatusOK {
		t.Fatalf("GET /projects/:id status = %d, body = %s, want 200", w.Code, w.Body.String())
	}
	var got projectResp
	if err := json.Unmarshal(w.Body.Bytes(), &got); err != nil {
		t.Fatalf("unmarshal body: %v", err)
	}
	if got.TeamID == nil || *got.TeamID != handlerTeamID {
		t.Errorf("GET /projects/:id teamId = %v, want %q", got.TeamID, handlerTeamID)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

// TestGetProjectDetailTeamNonMember 覆盖团队项目详情:非成员 403。
func TestGetProjectDetailTeamNonMember(t *testing.T) {
	r, mock, tokens := newProjectTestEnv(t)

	mock.ExpectQuery("FROM projects WHERE id").
		WithArgs(handlerProjectID).
		WillReturnRows(projectRow(handlerProjectID, "团队项目", nil, "production", handlerTeamID, "11111111-1111-1111-1111-111111111111"))
	mock.ExpectQuery("LEFT JOIN team_members").
		WithArgs(handlerTeamID, handlerUserID).
		WillReturnRows(membershipRow(false))

	w := doProjectRequest(t, r, tokens, http.MethodGet, "/api/v1/projects/"+handlerProjectID, "")
	if w.Code != http.StatusForbidden {
		t.Fatalf("GET /projects/:id status = %d, body = %s, want 403", w.Code, w.Body.String())
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

// TestGetProjectDetailNotFound 覆盖项目不存在:404。
func TestGetProjectDetailNotFound(t *testing.T) {
	r, mock, tokens := newProjectTestEnv(t)

	mock.ExpectQuery("FROM projects WHERE id").
		WithArgs(handlerProjectID).
		WillReturnError(sql.ErrNoRows)

	w := doProjectRequest(t, r, tokens, http.MethodGet, "/api/v1/projects/"+handlerProjectID, "")
	if w.Code != http.StatusNotFound {
		t.Fatalf("GET /projects/:id status = %d, body = %s, want 404", w.Code, w.Body.String())
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

// TestGetProjectDetailInvalidID 覆盖 P3:非 UUID 的 :id 返回 400,不触碰数据库。
func TestGetProjectDetailInvalidID(t *testing.T) {
	r, mock, tokens := newProjectTestEnv(t)

	w := doProjectRequest(t, r, tokens, http.MethodGet, "/api/v1/projects/not-a-uuid", "")
	if w.Code != http.StatusBadRequest {
		t.Fatalf("GET /projects/:id status = %d, body = %s, want 400", w.Code, w.Body.String())
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}
