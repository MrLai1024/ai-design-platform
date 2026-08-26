package store

import (
	"context"
	"database/sql"
	"fmt"
	"io/fs"
	"log/slog"
	"sort"
	"strings"
)

const (
	// createSchemaMigrationsTable 幂等创建迁移记录表。
	createSchemaMigrationsTable = `CREATE TABLE IF NOT EXISTS schema_migrations (version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())`
	selectAppliedVersions       = `SELECT version FROM schema_migrations`
	insertAppliedVersion        = `INSERT INTO schema_migrations (version, applied_at) VALUES ($1, now())`
)

// Migrator 按文件名排序执行 fs.FS 中的 .sql 迁移文件,
// 通过 schema_migrations 表保证幂等(已应用版本跳过)。
type Migrator struct {
	db *sql.DB
	fs fs.FS
}

// NewMigrator 创建迁移执行器。
func NewMigrator(db *sql.DB, fsys fs.FS) *Migrator {
	return &Migrator{db: db, fs: fsys}
}

// Run 执行全部未应用的迁移。每个迁移文件在一个事务中执行,
// 成功后将文件名(版本)写入 schema_migrations。
func (m *Migrator) Run(ctx context.Context) error {
	if _, err := m.db.ExecContext(ctx, createSchemaMigrationsTable); err != nil {
		return fmt.Errorf("create schema_migrations table: %w", err)
	}

	applied, err := m.appliedVersions(ctx)
	if err != nil {
		return err
	}

	entries, err := fs.ReadDir(m.fs, ".")
	if err != nil {
		return fmt.Errorf("read migrations dir: %w", err)
	}
	sort.Slice(entries, func(i, j int) bool { return entries[i].Name() < entries[j].Name() })

	for _, e := range entries {
		name := e.Name()
		if e.IsDir() || !strings.HasSuffix(name, ".sql") {
			continue
		}
		if applied[name] {
			continue
		}
		if err := m.apply(ctx, name); err != nil {
			return err
		}
	}
	return nil
}

func (m *Migrator) appliedVersions(ctx context.Context) (map[string]bool, error) {
	rows, err := m.db.QueryContext(ctx, selectAppliedVersions)
	if err != nil {
		return nil, fmt.Errorf("query schema_migrations: %w", err)
	}
	defer rows.Close()

	applied := make(map[string]bool)
	for rows.Next() {
		var version string
		if err := rows.Scan(&version); err != nil {
			return nil, fmt.Errorf("scan schema_migrations: %w", err)
		}
		applied[version] = true
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate schema_migrations: %w", err)
	}
	return applied, nil
}

func (m *Migrator) apply(ctx context.Context, name string) error {
	content, err := fs.ReadFile(m.fs, name)
	if err != nil {
		return fmt.Errorf("read migration %s: %w", name, err)
	}

	tx, err := m.db.BeginTx(ctx, nil)
	if err != nil {
		return fmt.Errorf("begin migration %s: %w", name, err)
	}
	// 提交后 Rollback 是 no-op,错误可忽略。
	defer tx.Rollback() //nolint:errcheck

	if _, err := tx.ExecContext(ctx, string(content)); err != nil {
		return fmt.Errorf("apply migration %s: %w", name, err)
	}
	if _, err := tx.ExecContext(ctx, insertAppliedVersion, name); err != nil {
		return fmt.Errorf("record migration %s: %w", name, err)
	}
	if err := tx.Commit(); err != nil {
		return fmt.Errorf("commit migration %s: %w", name, err)
	}
	slog.Info("migration applied", "version", name)
	return nil
}
