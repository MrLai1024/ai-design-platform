package store

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5/pgconn"
)

const (
	insertUser          = `INSERT INTO users (account, password) VALUES ($1, $2) RETURNING id, account, password, created_at`
	selectUserByAccount = `SELECT id, account, password, created_at FROM users WHERE account = $1`
	selectUserByID      = `SELECT id, account, password, created_at FROM users WHERE id = $1`
)

var (
	// ErrUserNotFound 查询不到用户时返回。
	ErrUserNotFound = errors.New("user not found")
	// ErrAccountConflict 账号已存在(唯一约束冲突)时返回。
	ErrAccountConflict = errors.New("account already exists")
)

// User 对应 users 表一行。
type User struct {
	ID        string
	Account   string
	Password  string
	CreatedAt time.Time
}

// Users 提供 users 表的数据访问。
type Users struct {
	db *sql.DB
}

// NewUsers 创建 Users。
func NewUsers(db *sql.DB) *Users { return &Users{db: db} }

// CreateUser 插入新用户并返回完整行。账号唯一约束冲突时返回 ErrAccountConflict。
func (s *Users) CreateUser(ctx context.Context, account, password string) (User, error) {
	var u User
	err := s.db.QueryRowContext(ctx, insertUser, account, password).
		Scan(&u.ID, &u.Account, &u.Password, &u.CreatedAt)
	if err != nil {
		var pgErr *pgconn.PgError
		if errors.As(err, &pgErr) && pgErr.Code == "23505" {
			return User{}, fmt.Errorf("%w: %s", ErrAccountConflict, account)
		}
		return User{}, fmt.Errorf("insert user %q: %w", account, err)
	}
	return u, nil
}

// GetUserByAccount 按账号查询用户,不存在时返回 ErrUserNotFound。
func (s *Users) GetUserByAccount(ctx context.Context, account string) (User, error) {
	var u User
	err := s.db.QueryRowContext(ctx, selectUserByAccount, account).
		Scan(&u.ID, &u.Account, &u.Password, &u.CreatedAt)
	if errors.Is(err, sql.ErrNoRows) {
		return User{}, ErrUserNotFound
	}
	if err != nil {
		return User{}, fmt.Errorf("select user by account %q: %w", account, err)
	}
	return u, nil
}

// GetUserByID 按 id 查询用户,不存在时返回 ErrUserNotFound。
func (s *Users) GetUserByID(ctx context.Context, id string) (User, error) {
	var u User
	err := s.db.QueryRowContext(ctx, selectUserByID, id).
		Scan(&u.ID, &u.Account, &u.Password, &u.CreatedAt)
	if errors.Is(err, sql.ErrNoRows) {
		return User{}, ErrUserNotFound
	}
	if err != nil {
		return User{}, fmt.Errorf("select user by id %q: %w", id, err)
	}
	return u, nil
}
