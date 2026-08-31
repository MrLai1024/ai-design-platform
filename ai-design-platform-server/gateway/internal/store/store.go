// Package store 提供 PostgreSQL 连接池与 users 表访问。
package store

import (
	"context"
	"database/sql"
	"fmt"
	"time"

	_ "github.com/jackc/pgx/v5/stdlib"
)

// NewPool 创建 PostgreSQL 连接池(database/sql + pgx stdlib 驱动)。
// 不建立实际连接,失败时由 Check 做启动自检。
func NewPool(databaseURL string) (*sql.DB, error) {
	db, err := sql.Open("pgx", databaseURL)
	if err != nil {
		return nil, fmt.Errorf("open database: %w", err)
	}
	db.SetMaxOpenConns(10)
	db.SetMaxIdleConns(5)
	db.SetConnMaxIdleTime(5 * time.Minute)
	db.SetConnMaxLifetime(30 * time.Minute)
	return db, nil
}

// Check 对连接池做启动自检(ping),失败返回错误,由调用方退出进程。
func Check(ctx context.Context, db *sql.DB) error {
	if err := db.PingContext(ctx); err != nil {
		return fmt.Errorf("ping database: %w", err)
	}
	return nil
}

// ensureUsersTable 幂等创建 users 表。
// users 表 DDL 归口 gateway(全局服务)唯一管理,project-service 迁移
// 只保留外键引用,不再建表;业务服务依赖 gateway 先启动完成建表
// (compose 已用 depends_on 约束顺序)。
const ensureUsersTable = `
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE TABLE IF NOT EXISTS users (
    id         uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    account    varchar(255) NOT NULL UNIQUE,
    password   varchar(255) NOT NULL,
    created_at timestamptz  NOT NULL DEFAULT now()
)`

// EnsureUsersTable 幂等确保 users 表存在(启动时调用)。
func EnsureUsersTable(ctx context.Context, db *sql.DB) error {
	if _, err := db.ExecContext(ctx, ensureUsersTable); err != nil {
		return fmt.Errorf("ensure users table: %w", err)
	}
	return nil
}
