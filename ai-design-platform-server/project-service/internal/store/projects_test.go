package store

import (
	"context"
	"database/sql"
	"errors"
	"strings"
	"testing"

	"github.com/DATA-DOG/go-sqlmock"
)

// fixedProjectID 是测试用的固定项目 id。
const fixedProjectID = "99999999-9999-9999-9999-999999999999"

// expectProjectRow 构造 projects 表一行数据的 sqlmock Rows。
// description/teamID 传 nil 表示库中为 NULL。
func expectProjectRow(id, name string, description any, level string, teamID any, createdBy string) *sqlmock.Rows {
	return sqlmock.NewRows([]string{"id", "name", "description", "level", "team_id", "created_by", "created_at"}).
		AddRow(id, name, description, level, teamID, createdBy, fixedCreatedAt)
}

// TestCreateProject 覆盖创建个人项目:team_id 参数落 NULL。
// newMockDB 使用 QueryMatcherEqual,SQL 必须与实现常量完全一致。
func TestCreateProject(t *testing.T) {
	db, mock := newMockDB(t)
	projects := NewProjects(db)

	mock.ExpectQuery(insertProject).
		WithArgs("个人项目", "项目简介", "demo", nil, fixedUserID).
		WillReturnRows(expectProjectRow(fixedProjectID, "个人项目", "项目简介", "demo", nil, fixedUserID))

	got, err := projects.Create(context.Background(), "个人项目", "项目简介", "demo", nil, fixedUserID)
	if err != nil {
		t.Fatalf("Create() error = %v, want nil", err)
	}
	if got.ID != fixedProjectID || got.Name != "个人项目" || got.Level != "demo" {
		t.Errorf("Create() = %+v, want project %s level demo", got, fixedProjectID)
	}
	if got.Description == nil || *got.Description != "项目简介" {
		t.Errorf("Create() Description = %v, want %q", got.Description, "项目简介")
	}
	if got.TeamID != nil {
		t.Errorf("Create() TeamID = %v, want nil (个人项目)", *got.TeamID)
	}
	if got.CreatedBy != fixedUserID {
		t.Errorf("Create() CreatedBy = %q, want %q", got.CreatedBy, fixedUserID)
	}
	if !got.CreatedAt.Equal(fixedCreatedAt) {
		t.Errorf("Create() CreatedAt = %v, want %v", got.CreatedAt, fixedCreatedAt)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

// TestCreateTeamProject 覆盖创建团队项目:team_id 参数传团队 id。
func TestCreateTeamProject(t *testing.T) {
	db, mock := newMockDB(t)
	projects := NewProjects(db)

	teamID := fixedTeamID
	mock.ExpectQuery(insertProject).
		WithArgs("团队项目", "简介", "production", teamID, fixedUserID).
		WillReturnRows(expectProjectRow(fixedProjectID, "团队项目", "简介", "production", teamID, fixedUserID))

	got, err := projects.Create(context.Background(), "团队项目", "简介", "production", &teamID, fixedUserID)
	if err != nil {
		t.Fatalf("Create() error = %v, want nil", err)
	}
	if got.TeamID == nil || *got.TeamID != fixedTeamID {
		t.Errorf("Create() TeamID = %v, want %q", got.TeamID, fixedTeamID)
	}
	if got.Level != "production" {
		t.Errorf("Create() Level = %q, want production", got.Level)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

// TestCreateProjectEmptyDescription 覆盖简介为空时落 NULL 的路径。
func TestCreateProjectEmptyDescription(t *testing.T) {
	db, mock := newMockDB(t)
	projects := NewProjects(db)

	mock.ExpectQuery(insertProject).
		WithArgs("个人项目", nil, "demo", nil, fixedUserID).
		WillReturnRows(expectProjectRow(fixedProjectID, "个人项目", nil, "demo", nil, fixedUserID))

	got, err := projects.Create(context.Background(), "个人项目", "", "demo", nil, fixedUserID)
	if err != nil {
		t.Fatalf("Create() error = %v, want nil", err)
	}
	if got.Description != nil {
		t.Errorf("Create() Description = %v, want nil (空描述落 NULL)", *got.Description)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

func TestCreateProjectError(t *testing.T) {
	db, mock := newMockDB(t)
	projects := NewProjects(db)

	mock.ExpectQuery(insertProject).
		WithArgs("个人项目", nil, "demo", nil, fixedUserID).
		WillReturnError(errors.New("connection refused"))

	_, err := projects.Create(context.Background(), "个人项目", "", "demo", nil, fixedUserID)
	if err == nil {
		t.Fatal("Create() error = nil, want insert error")
	}
	if !strings.Contains(err.Error(), "insert project") {
		t.Errorf("Create() error = %v, want it to wrap insert project context", err)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

// TestListPersonal 覆盖个人项目列表;Equal 匹配器同时断言了
// 过滤条件(team_id IS NULL AND created_by = 当前用户)与排序子句。
func TestListPersonal(t *testing.T) {
	db, mock := newMockDB(t)
	projects := NewProjects(db)

	mock.ExpectQuery(selectProjectsByUser).
		WithArgs(fixedUserID).
		WillReturnRows(
			expectProjectRow(fixedProjectID, "个人项目", "简介", "demo", nil, fixedUserID).
				AddRow("88888888-8888-8888-8888-888888888888", "生产项目", nil, "production", nil, fixedUserID, fixedCreatedAt),
		)

	got, err := projects.ListPersonal(context.Background(), fixedUserID)
	if err != nil {
		t.Fatalf("ListPersonal() error = %v, want nil", err)
	}
	if len(got) != 2 {
		t.Fatalf("ListPersonal() len = %d, want 2", len(got))
	}
	if got[0].ID != fixedProjectID || got[0].Name != "个人项目" || got[0].Level != "demo" {
		t.Errorf("ListPersonal()[0] = %+v, want project %s", got[0], fixedProjectID)
	}
	if got[0].TeamID != nil {
		t.Errorf("ListPersonal()[0] TeamID = %v, want nil (个人项目)", *got[0].TeamID)
	}
	if got[0].Description == nil || *got[0].Description != "简介" {
		t.Errorf("ListPersonal()[0] Description = %v, want %q", got[0].Description, "简介")
	}
	if got[1].Description != nil {
		t.Errorf("ListPersonal()[1] Description = %v, want nil (NULL 映射为 nil)", *got[1].Description)
	}
	if got[1].Level != "production" {
		t.Errorf("ListPersonal()[1] Level = %q, want production", got[1].Level)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

// TestListPersonalEmpty 覆盖空列表:返回非 nil 空切片(保证 JSON 序列化为 [] 而非 null)。
func TestListPersonalEmpty(t *testing.T) {
	db, mock := newMockDB(t)
	projects := NewProjects(db)

	mock.ExpectQuery(selectProjectsByUser).
		WithArgs(fixedUserID).
		WillReturnRows(sqlmock.NewRows([]string{"id", "name", "description", "level", "team_id", "created_by", "created_at"}))

	got, err := projects.ListPersonal(context.Background(), fixedUserID)
	if err != nil {
		t.Fatalf("ListPersonal() error = %v, want nil", err)
	}
	if got == nil {
		t.Fatal("ListPersonal() = nil, want empty non-nil slice")
	}
	if len(got) != 0 {
		t.Errorf("ListPersonal() len = %d, want 0", len(got))
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

func TestListPersonalError(t *testing.T) {
	db, mock := newMockDB(t)
	projects := NewProjects(db)

	mock.ExpectQuery(selectProjectsByUser).
		WithArgs(fixedUserID).
		WillReturnError(errors.New("connection refused"))

	_, err := projects.ListPersonal(context.Background(), fixedUserID)
	if err == nil {
		t.Fatal("ListPersonal() error = nil, want query error")
	}
	if !strings.Contains(err.Error(), "list personal projects") {
		t.Errorf("ListPersonal() error = %v, want it to wrap query context", err)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

// TestListByTeam 覆盖团队项目列表:team_id 过滤与排序子句。
func TestListByTeam(t *testing.T) {
	db, mock := newMockDB(t)
	projects := NewProjects(db)

	mock.ExpectQuery(selectProjectsByTeam).
		WithArgs(fixedTeamID).
		WillReturnRows(expectProjectRow(fixedProjectID, "团队项目", nil, "production", fixedTeamID, fixedUserID))

	got, err := projects.ListByTeam(context.Background(), fixedTeamID)
	if err != nil {
		t.Fatalf("ListByTeam() error = %v, want nil", err)
	}
	if len(got) != 1 {
		t.Fatalf("ListByTeam() len = %d, want 1", len(got))
	}
	if got[0].ID != fixedProjectID || got[0].TeamID == nil || *got[0].TeamID != fixedTeamID {
		t.Errorf("ListByTeam()[0] = %+v, want project %s of team %s", got[0], fixedProjectID, fixedTeamID)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

func TestListByTeamEmpty(t *testing.T) {
	db, mock := newMockDB(t)
	projects := NewProjects(db)

	mock.ExpectQuery(selectProjectsByTeam).
		WithArgs(fixedTeamID).
		WillReturnRows(sqlmock.NewRows([]string{"id", "name", "description", "level", "team_id", "created_by", "created_at"}))

	got, err := projects.ListByTeam(context.Background(), fixedTeamID)
	if err != nil {
		t.Fatalf("ListByTeam() error = %v, want nil", err)
	}
	if got == nil || len(got) != 0 {
		t.Errorf("ListByTeam() = %v, want empty non-nil slice", got)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

func TestListByTeamError(t *testing.T) {
	db, mock := newMockDB(t)
	projects := NewProjects(db)

	mock.ExpectQuery(selectProjectsByTeam).
		WithArgs(fixedTeamID).
		WillReturnError(errors.New("connection refused"))

	_, err := projects.ListByTeam(context.Background(), fixedTeamID)
	if err == nil {
		t.Fatal("ListByTeam() error = nil, want query error")
	}
	if !strings.Contains(err.Error(), "list team projects") {
		t.Errorf("ListByTeam() error = %v, want it to wrap query context", err)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

// TestGetProject 覆盖按 id 查询项目详情。
func TestGetProject(t *testing.T) {
	db, mock := newMockDB(t)
	projects := NewProjects(db)

	mock.ExpectQuery(selectProjectByID).
		WithArgs(fixedProjectID).
		WillReturnRows(expectProjectRow(fixedProjectID, "个人项目", "简介", "demo", nil, fixedUserID))

	got, err := projects.Get(context.Background(), fixedProjectID)
	if err != nil {
		t.Fatalf("Get() error = %v, want nil", err)
	}
	if got.ID != fixedProjectID || got.Name != "个人项目" || got.CreatedBy != fixedUserID {
		t.Errorf("Get() = %+v, want project %s created by %s", got, fixedProjectID, fixedUserID)
	}
	if got.TeamID != nil {
		t.Errorf("Get() TeamID = %v, want nil", *got.TeamID)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

func TestGetProjectNotFound(t *testing.T) {
	db, mock := newMockDB(t)
	projects := NewProjects(db)

	mock.ExpectQuery(selectProjectByID).
		WithArgs(fixedProjectID).
		WillReturnError(sql.ErrNoRows)

	_, err := projects.Get(context.Background(), fixedProjectID)
	if !errors.Is(err, ErrProjectNotFound) {
		t.Errorf("Get() error = %v, want ErrProjectNotFound", err)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

func TestGetProjectError(t *testing.T) {
	db, mock := newMockDB(t)
	projects := NewProjects(db)

	mock.ExpectQuery(selectProjectByID).
		WithArgs(fixedProjectID).
		WillReturnError(errors.New("connection refused"))

	_, err := projects.Get(context.Background(), fixedProjectID)
	if err == nil {
		t.Fatal("Get() error = nil, want query error")
	}
	if errors.Is(err, ErrProjectNotFound) {
		t.Errorf("Get() error = %v, must not be ErrProjectNotFound", err)
	}
	if !strings.Contains(err.Error(), "select project by id") {
		t.Errorf("Get() error = %v, want it to wrap query context", err)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

// TestIsMember 覆盖成员身份判定:一次查询同时判定团队存在性与成员身份。
func TestIsMember(t *testing.T) {
	db, mock := newMockDB(t)
	projects := NewProjects(db)

	mock.ExpectQuery(selectTeamMembership).
		WithArgs(fixedTeamID, fixedUserID).
		WillReturnRows(sqlmock.NewRows([]string{"is_member"}).AddRow(true))

	got, err := projects.IsMember(context.Background(), fixedTeamID, fixedUserID)
	if err != nil {
		t.Fatalf("IsMember() error = %v, want nil", err)
	}
	if !got {
		t.Error("IsMember() = false, want true")
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

// TestIsMemberFalse 覆盖团队存在但用户不是成员。
func TestIsMemberFalse(t *testing.T) {
	db, mock := newMockDB(t)
	projects := NewProjects(db)

	mock.ExpectQuery(selectTeamMembership).
		WithArgs(fixedTeamID, fixedUserID).
		WillReturnRows(sqlmock.NewRows([]string{"is_member"}).AddRow(false))

	got, err := projects.IsMember(context.Background(), fixedTeamID, fixedUserID)
	if err != nil {
		t.Fatalf("IsMember() error = %v, want nil", err)
	}
	if got {
		t.Error("IsMember() = true, want false")
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

// TestIsMemberTeamNotFound 覆盖团队不存在:0 行映射为 ErrTeamNotFound,
// 供 handler 区分 404(团队不存在)与 403(非成员)。
func TestIsMemberTeamNotFound(t *testing.T) {
	db, mock := newMockDB(t)
	projects := NewProjects(db)

	mock.ExpectQuery(selectTeamMembership).
		WithArgs(fixedTeamID, fixedUserID).
		WillReturnError(sql.ErrNoRows)

	_, err := projects.IsMember(context.Background(), fixedTeamID, fixedUserID)
	if !errors.Is(err, ErrTeamNotFound) {
		t.Errorf("IsMember() error = %v, want ErrTeamNotFound", err)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

func TestIsMemberError(t *testing.T) {
	db, mock := newMockDB(t)
	projects := NewProjects(db)

	mock.ExpectQuery(selectTeamMembership).
		WithArgs(fixedTeamID, fixedUserID).
		WillReturnError(errors.New("connection refused"))

	_, err := projects.IsMember(context.Background(), fixedTeamID, fixedUserID)
	if err == nil {
		t.Fatal("IsMember() error = nil, want query error")
	}
	if errors.Is(err, ErrTeamNotFound) {
		t.Errorf("IsMember() error = %v, must not be ErrTeamNotFound", err)
	}
	if !strings.Contains(err.Error(), "check membership") {
		t.Errorf("IsMember() error = %v, want it to wrap query context", err)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

// TestProjectListQueryOrder 覆盖排序契约:创建时间倒序,id 兜底,
// 同时间戳时顺序稳定不跳变。
func TestProjectListQueryOrder(t *testing.T) {
	for _, q := range []string{selectProjectsByUser, selectProjectsByTeam} {
		if !strings.Contains(q, "ORDER BY created_at DESC, id DESC") {
			t.Errorf("project list query %q, want ORDER BY created_at DESC, id DESC", q)
		}
	}
}
