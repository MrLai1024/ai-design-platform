package store

import (
	"context"
	"database/sql"
	"errors"
	"strings"
	"testing"
	"time"

	"github.com/DATA-DOG/go-sqlmock"
	"github.com/jackc/pgx/v5/pgconn"
)

// fixedUserID 是测试用的固定用户 id。
const fixedUserID = "11111111-1111-1111-1111-111111111111"

var fixedCreatedAt = time.Date(2026, 8, 25, 12, 0, 0, 0, time.UTC)

// expectUserRow 构造 users 表一行数据的 sqlmock Rows。
func expectUserRow(id, account, password string) *sqlmock.Rows {
	return sqlmock.NewRows([]string{"id", "account", "password", "created_at"}).
		AddRow(id, account, password, fixedCreatedAt)
}

func TestCreateUser(t *testing.T) {
	db, mock := newMockDB(t)
	users := NewUsers(db)

	mock.ExpectQuery(insertUser).
		WithArgs("user_abc", "pass-123").
		WillReturnRows(expectUserRow(fixedUserID, "user_abc", "pass-123"))

	got, err := users.CreateUser(context.Background(), "user_abc", "pass-123")
	if err != nil {
		t.Fatalf("CreateUser() error = %v, want nil", err)
	}
	if got.ID != fixedUserID {
		t.Errorf("CreateUser() ID = %q, want %q", got.ID, fixedUserID)
	}
	if got.Account != "user_abc" || got.Password != "pass-123" {
		t.Errorf("CreateUser() = (%q, %q), want (%q, %q)", got.Account, got.Password, "user_abc", "pass-123")
	}
	if !got.CreatedAt.Equal(fixedCreatedAt) {
		t.Errorf("CreateUser() CreatedAt = %v, want %v", got.CreatedAt, fixedCreatedAt)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

func TestCreateUserAccountConflict(t *testing.T) {
	db, mock := newMockDB(t)
	users := NewUsers(db)

	mock.ExpectQuery(insertUser).
		WithArgs("user_abc", "pass-123").
		WillReturnError(&pgconn.PgError{Code: "23505", Message: "duplicate key value violates unique constraint"})

	_, err := users.CreateUser(context.Background(), "user_abc", "pass-123")
	if !errors.Is(err, ErrAccountConflict) {
		t.Errorf("CreateUser() error = %v, want ErrAccountConflict", err)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

func TestCreateUserOtherError(t *testing.T) {
	db, mock := newMockDB(t)
	users := NewUsers(db)

	mock.ExpectQuery(insertUser).
		WithArgs("user_abc", "pass-123").
		WillReturnError(errors.New("connection refused"))

	_, err := users.CreateUser(context.Background(), "user_abc", "pass-123")
	if err == nil {
		t.Fatal("CreateUser() error = nil, want error")
	}
	if errors.Is(err, ErrAccountConflict) {
		t.Errorf("CreateUser() error = %v, must not be ErrAccountConflict", err)
	}
	if !strings.Contains(err.Error(), "insert user") {
		t.Errorf("CreateUser() error = %v, want it to wrap insert context", err)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

func TestGetUserByAccount(t *testing.T) {
	db, mock := newMockDB(t)
	users := NewUsers(db)

	mock.ExpectQuery(selectUserByAccount).
		WithArgs("user_abc").
		WillReturnRows(expectUserRow(fixedUserID, "user_abc", "pass-123"))

	got, err := users.GetUserByAccount(context.Background(), "user_abc")
	if err != nil {
		t.Fatalf("GetUserByAccount() error = %v, want nil", err)
	}
	if got.ID != fixedUserID || got.Account != "user_abc" || got.Password != "pass-123" {
		t.Errorf("GetUserByAccount() = %+v, want user_abc row", got)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

func TestGetUserByAccountNotFound(t *testing.T) {
	db, mock := newMockDB(t)
	users := NewUsers(db)

	mock.ExpectQuery(selectUserByAccount).
		WithArgs("nope").
		WillReturnError(sql.ErrNoRows)

	_, err := users.GetUserByAccount(context.Background(), "nope")
	if !errors.Is(err, ErrUserNotFound) {
		t.Errorf("GetUserByAccount() error = %v, want ErrUserNotFound", err)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

func TestGetUserByID(t *testing.T) {
	db, mock := newMockDB(t)
	users := NewUsers(db)

	mock.ExpectQuery(selectUserByID).
		WithArgs(fixedUserID).
		WillReturnRows(expectUserRow(fixedUserID, "user_abc", "pass-123"))

	got, err := users.GetUserByID(context.Background(), fixedUserID)
	if err != nil {
		t.Fatalf("GetUserByID() error = %v, want nil", err)
	}
	if got.Account != "user_abc" {
		t.Errorf("GetUserByID() Account = %q, want %q", got.Account, "user_abc")
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}

func TestGetUserByIDNotFound(t *testing.T) {
	db, mock := newMockDB(t)
	users := NewUsers(db)

	mock.ExpectQuery(selectUserByID).
		WithArgs(fixedUserID).
		WillReturnError(sql.ErrNoRows)

	_, err := users.GetUserByID(context.Background(), fixedUserID)
	if !errors.Is(err, ErrUserNotFound) {
		t.Errorf("GetUserByID() error = %v, want ErrUserNotFound", err)
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("unmet expectations: %v", err)
	}
}
