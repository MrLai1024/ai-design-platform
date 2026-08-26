package store

import (
	"context"
	"errors"
	"strings"
	"testing"

	"github.com/DATA-DOG/go-sqlmock"
	"github.com/jackc/pgx/v5/pgconn"
)

// fixedTeamID 是测试用的固定团队 id。
const fixedTeamID = "44444444-4444-4444-4444-444444444444"

// expectTeamRow 构造 teams 表一行数据的 sqlmock Rows。
// description 传 nil 表示库中为 NULL。
func expectTeamRow(id, name string, description any, ownerID string) *sqlmock.Rows {
	return sqlmock.NewRows([]string{"id", "name", "description", "owner_id", "created_at"}).
		AddRow(id, name, description, ownerID, fixedCreatedAt)
}

// TestCreateTeam 覆盖创建成功路径:插入 teams + 创建者成员记录,单事务提交。
// newMockDB 使用 QueryMatcherEqual,ExpectQuery/Exec 的 SQL 必须与实现常量完全一致。
func TestCreateTeam(t *testing.T) {
	db, mock := newMockDB(t)
	teams := NewTeams(db)

	mock.ExpectBegin()
	mock.ExpectQuery(insertTeam).
		WithArgs("设计组", "团队描述", fixedUserID).
		WillReturnRows(expectTeamRow(fixedTeamID, "设计组", "团队描述", fixedUserID))
	mock.ExpectExec(insertTeamMember).
		WithArgs(fixedTeamID, fixedUserID).
		WillReturnResult(sqlmock.NewResult(1, 1))
	mock.ExpectCommit()

	got, err := teams.CreateTeam(context.Background(), "设计组", "团队描述", fixedUserID)
	if err != nil {
		t.Fatalf("CreateTeam() error = %v, want nil", err)
	}
	if got.ID != fixedTeamID || got.Name != "设计组" || got.OwnerID != fixedUserID {
		t.Errorf("CreateTeam() = %+v, want team %s owned by %s", got, fixedTeamID, fixedUserID)
	}
	if got.Description == nil || *got.Description != "团队描述" {
		t.Errorf("CreateTeam() Description = %v, want %q", got.Description, "团队描述")
	}
	if !got.CreatedAt.Equal(fixedCreatedAt) {
		t.Errorf("CreateTeam() CreatedAt = %v, want %v", got.CreatedAt, fixedCreatedAt)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

// TestCreateTeamNilDescription 覆盖描述为空时落 NULL 的路径。
func TestCreateTeamNilDescription(t *testing.T) {
	db, mock := newMockDB(t)
	teams := NewTeams(db)

	mock.ExpectBegin()
	mock.ExpectQuery(insertTeam).
		WithArgs("设计组", nil, fixedUserID).
		WillReturnRows(expectTeamRow(fixedTeamID, "设计组", nil, fixedUserID))
	mock.ExpectExec(insertTeamMember).
		WithArgs(fixedTeamID, fixedUserID).
		WillReturnResult(sqlmock.NewResult(1, 1))
	mock.ExpectCommit()

	got, err := teams.CreateTeam(context.Background(), "设计组", "", fixedUserID)
	if err != nil {
		t.Fatalf("CreateTeam() error = %v, want nil", err)
	}
	if got.Description != nil {
		t.Errorf("CreateTeam() Description = %v, want nil (空描述落 NULL)", *got.Description)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

func TestCreateTeamBeginError(t *testing.T) {
	db, mock := newMockDB(t)
	teams := NewTeams(db)

	mock.ExpectBegin().WillReturnError(errors.New("begin failed"))

	_, err := teams.CreateTeam(context.Background(), "设计组", "", fixedUserID)
	if err == nil {
		t.Fatal("CreateTeam() error = nil, want begin error")
	}
	if !strings.Contains(err.Error(), "begin create team") {
		t.Errorf("CreateTeam() error = %v, want it to wrap begin context", err)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

// TestCreateTeamTeamInsertError 覆盖插入 teams 失败时回滚事务。
func TestCreateTeamTeamInsertError(t *testing.T) {
	db, mock := newMockDB(t)
	teams := NewTeams(db)

	mock.ExpectBegin()
	mock.ExpectQuery(insertTeam).
		WithArgs("设计组", nil, fixedUserID).
		WillReturnError(errors.New("connection refused"))
	mock.ExpectRollback()

	_, err := teams.CreateTeam(context.Background(), "设计组", "", fixedUserID)
	if err == nil {
		t.Fatal("CreateTeam() error = nil, want insert error")
	}
	if !strings.Contains(err.Error(), "insert team") {
		t.Errorf("CreateTeam() error = %v, want it to wrap insert team context", err)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

// TestCreateTeamMemberInsertError 覆盖创建者成员写入失败时回滚整个事务(团队不落库)。
func TestCreateTeamMemberInsertError(t *testing.T) {
	db, mock := newMockDB(t)
	teams := NewTeams(db)

	mock.ExpectBegin()
	mock.ExpectQuery(insertTeam).
		WithArgs("设计组", nil, fixedUserID).
		WillReturnRows(expectTeamRow(fixedTeamID, "设计组", nil, fixedUserID))
	mock.ExpectExec(insertTeamMember).
		WithArgs(fixedTeamID, fixedUserID).
		WillReturnError(errors.New("member insert failed"))
	mock.ExpectRollback()

	_, err := teams.CreateTeam(context.Background(), "设计组", "", fixedUserID)
	if err == nil {
		t.Fatal("CreateTeam() error = nil, want member insert error")
	}
	if !strings.Contains(err.Error(), "insert creator member") {
		t.Errorf("CreateTeam() error = %v, want it to wrap member insert context", err)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

func TestCreateTeamCommitError(t *testing.T) {
	db, mock := newMockDB(t)
	teams := NewTeams(db)

	mock.ExpectBegin()
	mock.ExpectQuery(insertTeam).
		WithArgs("设计组", nil, fixedUserID).
		WillReturnRows(expectTeamRow(fixedTeamID, "设计组", nil, fixedUserID))
	mock.ExpectExec(insertTeamMember).
		WithArgs(fixedTeamID, fixedUserID).
		WillReturnResult(sqlmock.NewResult(1, 1))
	mock.ExpectCommit().WillReturnError(errors.New("commit failed"))

	_, err := teams.CreateTeam(context.Background(), "设计组", "", fixedUserID)
	if err == nil {
		t.Fatal("CreateTeam() error = nil, want commit error")
	}
	if !strings.Contains(err.Error(), "commit create team") {
		t.Errorf("CreateTeam() error = %v, want it to wrap commit context", err)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

// TestListByUserOrderTiebreaker 覆盖 P1 修复:排序带 id 兜底,
// 同时间戳时顺序稳定,不随扫描顺序跳变。
func TestListByUserOrderTiebreaker(t *testing.T) {
	if !strings.Contains(selectTeamsByUser, "ORDER BY tm.joined_at DESC, t.created_at DESC, t.id DESC") {
		t.Errorf("selectTeamsByUser = %q, want ORDER BY with t.id DESC tiebreaker", selectTeamsByUser)
	}
}

// TestListByUser 覆盖列表查询;Equal 匹配器同时断言了排序子句
// (ORDER BY tm.joined_at DESC, t.created_at DESC, t.id DESC)。
func TestListByUser(t *testing.T) {
	db, mock := newMockDB(t)
	teams := NewTeams(db)

	mock.ExpectQuery(selectTeamsByUser).
		WithArgs(fixedUserID).
		WillReturnRows(
			expectTeamRow(fixedTeamID, "设计组", "团队描述", fixedUserID).
				AddRow("55555555-5555-5555-5555-555555555555", "研发组", nil, fixedUserID, fixedCreatedAt),
		)

	got, err := teams.ListByUser(context.Background(), fixedUserID)
	if err != nil {
		t.Fatalf("ListByUser() error = %v, want nil", err)
	}
	if len(got) != 2 {
		t.Fatalf("ListByUser() len = %d, want 2", len(got))
	}
	if got[0].ID != fixedTeamID || got[0].Name != "设计组" {
		t.Errorf("ListByUser()[0] = %+v, want team %s", got[0], fixedTeamID)
	}
	if got[0].Description == nil || *got[0].Description != "团队描述" {
		t.Errorf("ListByUser()[0] Description = %v, want %q", got[0].Description, "团队描述")
	}
	if got[1].Description != nil {
		t.Errorf("ListByUser()[1] Description = %v, want nil (NULL 映射为 nil)", *got[1].Description)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

// TestListByUserEmpty 覆盖空列表:返回非 nil 空切片(保证 JSON 序列化为 [] 而非 null)。
func TestListByUserEmpty(t *testing.T) {
	db, mock := newMockDB(t)
	teams := NewTeams(db)

	mock.ExpectQuery(selectTeamsByUser).
		WithArgs(fixedUserID).
		WillReturnRows(sqlmock.NewRows([]string{"id", "name", "description", "owner_id", "created_at"}))

	got, err := teams.ListByUser(context.Background(), fixedUserID)
	if err != nil {
		t.Fatalf("ListByUser() error = %v, want nil", err)
	}
	if got == nil {
		t.Fatal("ListByUser() = nil, want empty non-nil slice")
	}
	if len(got) != 0 {
		t.Errorf("ListByUser() len = %d, want 0", len(got))
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

func TestListByUserError(t *testing.T) {
	db, mock := newMockDB(t)
	teams := NewTeams(db)

	mock.ExpectQuery(selectTeamsByUser).
		WithArgs(fixedUserID).
		WillReturnError(errors.New("connection refused"))

	_, err := teams.ListByUser(context.Background(), fixedUserID)
	if err == nil {
		t.Fatal("ListByUser() error = nil, want query error")
	}
	if !strings.Contains(err.Error(), "list teams by user") {
		t.Errorf("ListByUser() error = %v, want it to wrap query context", err)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

// TestSearchByNameOrderTiebreaker 覆盖排序兜底:搜索排序带 id 兜底,
// 同时间戳时顺序稳定,不随扫描顺序跳变。
func TestSearchByNameOrderTiebreaker(t *testing.T) {
	if !strings.Contains(selectTeamsByKeyword, "ORDER BY t.created_at DESC, t.id DESC") {
		t.Errorf("selectTeamsByKeyword = %q, want ORDER BY with t.id DESC tiebreaker", selectTeamsByKeyword)
	}
}

// TestSearchByName 覆盖按名称模糊匹配;Equal 匹配器同时断言了
// ILIKE 模糊匹配、NOT EXISTS 排除已加入团队及 ORDER BY 排序子句。
func TestSearchByName(t *testing.T) {
	db, mock := newMockDB(t)
	teams := NewTeams(db)

	mock.ExpectQuery(selectTeamsByKeyword).
		WithArgs("%设计%", fixedUserID).
		WillReturnRows(expectTeamRow(fixedTeamID, "设计组", nil, fixedUserID))

	got, err := teams.SearchByName(context.Background(), "设计", fixedUserID)
	if err != nil {
		t.Fatalf("SearchByName() error = %v, want nil", err)
	}
	if len(got) != 1 || got[0].ID != fixedTeamID || got[0].Name != "设计组" {
		t.Errorf("SearchByName() = %+v, want team %s", got, fixedTeamID)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

func TestSearchByNameError(t *testing.T) {
	db, mock := newMockDB(t)
	teams := NewTeams(db)

	mock.ExpectQuery(selectTeamsByKeyword).
		WithArgs("%设计%", fixedUserID).
		WillReturnError(errors.New("connection refused"))

	_, err := teams.SearchByName(context.Background(), "设计", fixedUserID)
	if err == nil {
		t.Fatal("SearchByName() error = nil, want query error")
	}
	if !strings.Contains(err.Error(), "search teams") {
		t.Errorf("SearchByName() error = %v, want it to wrap query context", err)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

func TestJoinTeam(t *testing.T) {
	db, mock := newMockDB(t)
	teams := NewTeams(db)

	mock.ExpectExec(joinTeamMember).
		WithArgs(fixedTeamID, fixedUserID).
		WillReturnResult(sqlmock.NewResult(0, 1))

	if err := teams.JoinTeam(context.Background(), fixedTeamID, fixedUserID); err != nil {
		t.Fatalf("JoinTeam() error = %v, want nil", err)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

// TestJoinTeamConflict 覆盖重复加入:唯一约束冲突映射为 ErrMemberConflict。
func TestJoinTeamConflict(t *testing.T) {
	db, mock := newMockDB(t)
	teams := NewTeams(db)

	mock.ExpectExec(joinTeamMember).
		WithArgs(fixedTeamID, fixedUserID).
		WillReturnError(&pgconn.PgError{Code: "23505", Message: "duplicate key value violates unique constraint"})

	err := teams.JoinTeam(context.Background(), fixedTeamID, fixedUserID)
	if !errors.Is(err, ErrMemberConflict) {
		t.Errorf("JoinTeam() error = %v, want ErrMemberConflict", err)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

// TestJoinTeamNotFound 覆盖团队不存在:INSERT...SELECT 命中 0 行映射为 ErrTeamNotFound。
func TestJoinTeamNotFound(t *testing.T) {
	db, mock := newMockDB(t)
	teams := NewTeams(db)

	mock.ExpectExec(joinTeamMember).
		WithArgs(fixedTeamID, fixedUserID).
		WillReturnResult(sqlmock.NewResult(0, 0))

	err := teams.JoinTeam(context.Background(), fixedTeamID, fixedUserID)
	if !errors.Is(err, ErrTeamNotFound) {
		t.Errorf("JoinTeam() error = %v, want ErrTeamNotFound", err)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

func TestJoinTeamOtherError(t *testing.T) {
	db, mock := newMockDB(t)
	teams := NewTeams(db)

	mock.ExpectExec(joinTeamMember).
		WithArgs(fixedTeamID, fixedUserID).
		WillReturnError(errors.New("connection refused"))

	err := teams.JoinTeam(context.Background(), fixedTeamID, fixedUserID)
	if err == nil {
		t.Fatal("JoinTeam() error = nil, want exec error")
	}
	if errors.Is(err, ErrMemberConflict) || errors.Is(err, ErrTeamNotFound) {
		t.Errorf("JoinTeam() error = %v, must not be a sentinel error", err)
	}
	if !strings.Contains(err.Error(), "join team") {
		t.Errorf("JoinTeam() error = %v, want it to wrap join context", err)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}
