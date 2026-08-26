package migrations

import (
	"io/fs"
	"strings"
	"testing"
)

func TestMigrationsEmbedded(t *testing.T) {
	entries, err := fs.ReadDir(FS, ".")
	if err != nil {
		t.Fatalf("ReadDir() error = %v, want nil", err)
	}
	if len(entries) == 0 {
		t.Fatal("no migration files embedded")
	}

	found := map[string]bool{}
	for _, e := range entries {
		if e.IsDir() {
			t.Errorf("unexpected directory entry %q", e.Name())
			continue
		}
		if !strings.HasSuffix(e.Name(), ".sql") {
			t.Errorf("unexpected non-SQL entry %q", e.Name())
		}
		found[e.Name()] = true
	}
	for _, want := range []string{"0001_init.sql", "0002_team_project_indexes.sql"} {
		if !found[want] {
			t.Errorf("%s not embedded", want)
		}
	}
}

func TestInitMigrationContent(t *testing.T) {
	content, err := fs.ReadFile(FS, "0001_init.sql")
	if err != nil {
		t.Fatalf("ReadFile(0001_init.sql) error = %v", err)
	}
	// 归一化空白(SQL 中列对齐的多空格不影响校验)。
	normalized := strings.Join(strings.Fields(string(content)), " ")

	// 四张表 + 幂等 DDL + 关键约束。
	for _, want := range []string{
		"CREATE EXTENSION IF NOT EXISTS pgcrypto",
		"CREATE TABLE IF NOT EXISTS users",
		"CREATE TABLE IF NOT EXISTS teams",
		"CREATE TABLE IF NOT EXISTS team_members",
		"CREATE TABLE IF NOT EXISTS projects",
		"gen_random_uuid()",
		"account varchar(255) NOT NULL UNIQUE",
		"PRIMARY KEY (team_id, user_id)",
		"CHECK (level IN ('demo', 'production'))",
		"REFERENCES users (id)",
		"REFERENCES teams (id)",
	} {
		if !strings.Contains(normalized, want) {
			t.Errorf("0001_init.sql missing %q", want)
		}
	}
}

func TestSecondMigrationContent(t *testing.T) {
	content, err := fs.ReadFile(FS, "0002_team_project_indexes.sql")
	if err != nil {
		t.Fatalf("ReadFile(0002_team_project_indexes.sql) error = %v", err)
	}
	normalized := strings.Join(strings.Fields(string(content)), " ")

	// 四个二级索引,全部 IF NOT EXISTS 幂等。
	for _, want := range []string{
		"CREATE INDEX IF NOT EXISTS idx_team_members_user_id ON team_members (user_id)",
		"CREATE INDEX IF NOT EXISTS idx_projects_team_id ON projects (team_id)",
		"CREATE INDEX IF NOT EXISTS idx_projects_created_by ON projects (created_by) WHERE team_id IS NULL",
		"CREATE INDEX IF NOT EXISTS idx_teams_owner_id ON teams (owner_id)",
	} {
		if !strings.Contains(normalized, want) {
			t.Errorf("0002_team_project_indexes.sql missing %q", want)
		}
	}
}

// TestSecondMigrationOwnerIndexComment 覆盖 P2 修复:idx_teams_owner_id 需注明
// "预留:当前无按 owner 查询路径",避免后续误以为存在查询路径而依赖该索引。
func TestSecondMigrationOwnerIndexComment(t *testing.T) {
	content, err := fs.ReadFile(FS, "0002_team_project_indexes.sql")
	if err != nil {
		t.Fatalf("ReadFile(0002_team_project_indexes.sql) error = %v", err)
	}
	if !strings.Contains(string(content), "预留:当前无按 owner 查询路径") {
		t.Errorf("0002_team_project_indexes.sql 缺少 idx_teams_owner_id 的预留注释")
	}
}
