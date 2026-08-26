// Package store 提供 PostgreSQL 连接池与启动迁移。
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
