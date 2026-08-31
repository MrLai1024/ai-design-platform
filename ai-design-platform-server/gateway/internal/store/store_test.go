package store

import (
	"context"
	"database/sql"
	"testing"

	"github.com/DATA-DOG/go-sqlmock"
)

// newMockDB 创建使用 QueryMatcherEqual 的 sqlmock 连接,测试结束后自动关闭。
// 使用 Equal 匹配器避免 QueryMatcherRegexp 把 SQL 中的 $1 当作正则锚点。
func newMockDB(t *testing.T) (*sql.DB, sqlmock.Sqlmock) {
	t.Helper()
	db, mock, err := sqlmock.New(sqlmock.QueryMatcherOption(sqlmock.QueryMatcherEqual))
	if err != nil {
		t.Fatalf("sqlmock.New() error = %v", err)
	}
	t.Cleanup(func() { db.Close() })
	return db, mock
}

// TestEnsureUsersTable 验证兜底建表语句(单次 Exec 含扩展与建表两条语句)幂等执行。
func TestEnsureUsersTable(t *testing.T) {
	db, mock := newMockDB(t)

	mock.ExpectExec(ensureUsersTable).
		WillReturnResult(sqlmock.NewResult(0, 0))

	if err := EnsureUsersTable(context.Background(), db); err != nil {
		t.Fatalf("EnsureUsersTable() error = %v, want nil", err)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

// TestEnsureUsersTableError 验证建表失败时返回错误。
func TestEnsureUsersTableError(t *testing.T) {
	db, mock := newMockDB(t)

	mock.ExpectExec(ensureUsersTable).
		WillReturnError(sql.ErrConnDone)

	if err := EnsureUsersTable(context.Background(), db); err == nil {
		t.Fatal("EnsureUsersTable() error = nil, want error")
	}
}
