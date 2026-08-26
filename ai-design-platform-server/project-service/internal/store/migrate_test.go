package store

import (
	"context"
	"database/sql"
	"errors"
	"io/fs"
	"strings"
	"testing"
	"testing/fstest"

	"github.com/DATA-DOG/go-sqlmock"
)

// newMockDB 创建使用 QueryMatcherEqual 的 sqlmock 连接。
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

func TestMigrateSkipsAppliedVersions(t *testing.T) {
	db, mock := newMockDB(t)
	m := NewMigrator(db, fstest.MapFS{
		"0001_init.sql": &fstest.MapFile{Data: []byte("CREATE TABLE IF NOT EXISTS users (id uuid PRIMARY KEY);")},
	})

	mock.ExpectExec(createSchemaMigrationsTable).WillReturnResult(sqlmock.NewResult(0, 0))
	mock.ExpectQuery(selectAppliedVersions).
		WillReturnRows(sqlmock.NewRows([]string{"version"}).AddRow("0001_init.sql"))

	if err := m.Run(context.Background()); err != nil {
		t.Fatalf("Run() error = %v, want nil", err)
	}
	// 已应用版本不应触发 Begin/Exec,否则会有未匹配的调用。
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

func TestMigrateAppliesPendingInFilenameOrder(t *testing.T) {
	db, mock := newMockDB(t)
	m := NewMigrator(db, fstest.MapFS{
		"0002_b.sql": &fstest.MapFile{Data: []byte("CREATE TABLE IF NOT EXISTS b (id int);")},
		"0001_a.sql": &fstest.MapFile{Data: []byte("CREATE TABLE IF NOT EXISTS a (id int);")},
	})

	mock.ExpectExec(createSchemaMigrationsTable).WillReturnResult(sqlmock.NewResult(0, 0))
	mock.ExpectQuery(selectAppliedVersions).WillReturnRows(sqlmock.NewRows([]string{"version"}))

	// sqlmock 默认按声明顺序匹配,先 a 后 b 即验证了文件名排序。
	mock.ExpectBegin()
	mock.ExpectExec("CREATE TABLE IF NOT EXISTS a (id int);").WillReturnResult(sqlmock.NewResult(0, 0))
	mock.ExpectExec(insertAppliedVersion).WithArgs("0001_a.sql").WillReturnResult(sqlmock.NewResult(1, 1))
	mock.ExpectCommit()

	mock.ExpectBegin()
	mock.ExpectExec("CREATE TABLE IF NOT EXISTS b (id int);").WillReturnResult(sqlmock.NewResult(0, 0))
	mock.ExpectExec(insertAppliedVersion).WithArgs("0002_b.sql").WillReturnResult(sqlmock.NewResult(1, 1))
	mock.ExpectCommit()

	if err := m.Run(context.Background()); err != nil {
		t.Fatalf("Run() error = %v, want nil", err)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

func TestMigrateAppliesOnlyPending(t *testing.T) {
	db, mock := newMockDB(t)
	m := NewMigrator(db, fstest.MapFS{
		"0001_a.sql": &fstest.MapFile{Data: []byte("CREATE TABLE IF NOT EXISTS a (id int);")},
		"0002_b.sql": &fstest.MapFile{Data: []byte("CREATE TABLE IF NOT EXISTS b (id int);")},
	})

	mock.ExpectExec(createSchemaMigrationsTable).WillReturnResult(sqlmock.NewResult(0, 0))
	mock.ExpectQuery(selectAppliedVersions).
		WillReturnRows(sqlmock.NewRows([]string{"version"}).AddRow("0001_a.sql"))

	// 仅 0002_b.sql 未应用。
	mock.ExpectBegin()
	mock.ExpectExec("CREATE TABLE IF NOT EXISTS b (id int);").WillReturnResult(sqlmock.NewResult(0, 0))
	mock.ExpectExec(insertAppliedVersion).WithArgs("0002_b.sql").WillReturnResult(sqlmock.NewResult(1, 1))
	mock.ExpectCommit()

	if err := m.Run(context.Background()); err != nil {
		t.Fatalf("Run() error = %v, want nil", err)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

func TestMigrateNoFiles(t *testing.T) {
	db, mock := newMockDB(t)
	m := NewMigrator(db, fstest.MapFS{})

	mock.ExpectExec(createSchemaMigrationsTable).WillReturnResult(sqlmock.NewResult(0, 0))
	mock.ExpectQuery(selectAppliedVersions).WillReturnRows(sqlmock.NewRows([]string{"version"}))

	if err := m.Run(context.Background()); err != nil {
		t.Fatalf("Run() error = %v, want nil", err)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

func TestMigrateRollsBackOnError(t *testing.T) {
	db, mock := newMockDB(t)
	m := NewMigrator(db, fstest.MapFS{
		"0001_a.sql": &fstest.MapFile{Data: []byte("CREATE TABLE IF NOT EXISTS a (id int);")},
	})

	mock.ExpectExec(createSchemaMigrationsTable).WillReturnResult(sqlmock.NewResult(0, 0))
	mock.ExpectQuery(selectAppliedVersions).WillReturnRows(sqlmock.NewRows([]string{"version"}))

	mock.ExpectBegin()
	mock.ExpectExec("CREATE TABLE IF NOT EXISTS a (id int);").
		WillReturnError(errors.New("syntax error"))
	mock.ExpectRollback()

	if err := m.Run(context.Background()); err == nil {
		t.Fatal("Run() error = nil, want error from failed migration")
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

func TestMigrateRowsIterationError(t *testing.T) {
	db, mock := newMockDB(t)
	m := NewMigrator(db, fstest.MapFS{
		"0001_a.sql": &fstest.MapFile{Data: []byte("CREATE TABLE IF NOT EXISTS a (id int);")},
	})

	mock.ExpectExec(createSchemaMigrationsTable).WillReturnResult(sqlmock.NewResult(0, 0))
	mock.ExpectQuery(selectAppliedVersions).
		WillReturnRows(sqlmock.NewRows([]string{"version"}).
			AddRow("0001_a.sql").
			RowError(0, errors.New("connection reset")))

	err := m.Run(context.Background())
	if err == nil {
		t.Fatal("Run() error = nil, want rows iteration error")
	}
	if want := "iterate schema_migrations"; !strings.Contains(err.Error(), want) {
		t.Errorf("Run() error = %v, want it to contain %q", err, want)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

func TestMigrateCommitError(t *testing.T) {
	db, mock := newMockDB(t)
	m := NewMigrator(db, fstest.MapFS{
		"0001_a.sql": &fstest.MapFile{Data: []byte("CREATE TABLE IF NOT EXISTS a (id int);")},
	})

	mock.ExpectExec(createSchemaMigrationsTable).WillReturnResult(sqlmock.NewResult(0, 0))
	mock.ExpectQuery(selectAppliedVersions).WillReturnRows(sqlmock.NewRows([]string{"version"}))

	mock.ExpectBegin()
	mock.ExpectExec("CREATE TABLE IF NOT EXISTS a (id int);").WillReturnResult(sqlmock.NewResult(0, 0))
	mock.ExpectExec(insertAppliedVersion).WithArgs("0001_a.sql").WillReturnResult(sqlmock.NewResult(1, 1))
	mock.ExpectCommit().WillReturnError(errors.New("commit failed"))

	err := m.Run(context.Background())
	if err == nil {
		t.Fatal("Run() error = nil, want commit error")
	}
	if want := "commit migration 0001_a.sql"; !strings.Contains(err.Error(), want) {
		t.Errorf("Run() error = %v, want it to contain %q", err, want)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

// failReadFS 模拟"目录可正常列出、读取文件内容时报错"的文件系统,
// 用于覆盖迁移 apply 阶段的 fs 读取失败分支。
// 注意:内嵌 MapFS 会提升 ReadFile 方法,导致 fs.ReadFile 走
// MapFS 的快路径而绕过 Open,因此必须显式覆盖 ReadFile。
type failReadFS struct{ fstest.MapFS }

func (f failReadFS) Open(name string) (fs.File, error) {
	if name == "." {
		// 目录列表走内嵌 MapFS,保证 ReadDir 成功。
		return f.MapFS.Open(name)
	}
	return failReadFile{}, nil
}

func (failReadFS) ReadFile(string) ([]byte, error) {
	return nil, errors.New("read failed")
}

type failReadFile struct{}

func (failReadFile) Stat() (fs.FileInfo, error) { return nil, errors.New("stat failed") }
func (failReadFile) Read([]byte) (int, error)   { return 0, errors.New("read failed") }
func (failReadFile) Close() error               { return nil }

func TestMigrateReadFileError(t *testing.T) {
	db, mock := newMockDB(t)
	m := NewMigrator(db, failReadFS{MapFS: fstest.MapFS{
		"0001_a.sql": &fstest.MapFile{Data: []byte("CREATE TABLE IF NOT EXISTS a (id int);")},
	}})

	mock.ExpectExec(createSchemaMigrationsTable).WillReturnResult(sqlmock.NewResult(0, 0))
	mock.ExpectQuery(selectAppliedVersions).WillReturnRows(sqlmock.NewRows([]string{"version"}))

	err := m.Run(context.Background())
	if err == nil {
		t.Fatal("Run() error = nil, want read file error")
	}
	if want := "read migration 0001_a.sql"; !strings.Contains(err.Error(), want) {
		t.Errorf("Run() error = %v, want it to contain %q", err, want)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}
