package store

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"time"
)

const (
	insertProject        = `INSERT INTO projects (name, description, level, team_id, created_by) VALUES ($1, $2, $3, $4, $5) RETURNING id, name, description, level, team_id, created_by, created_at`
	selectProjectsByUser = `SELECT id, name, description, level, team_id, created_by, created_at FROM projects WHERE team_id IS NULL AND created_by = $1 ORDER BY created_at DESC, id DESC`
	selectProjectsByTeam = `SELECT id, name, description, level, team_id, created_by, created_at FROM projects WHERE team_id = $1 ORDER BY created_at DESC, id DESC`
	selectProjectByID    = `SELECT id, name, description, level, team_id, created_by, created_at FROM projects WHERE id = $1`
	// selectTeamMembership 以团队行 LEFT JOIN 成员行,一次查询同时判定
	// 团队存在性(0 行 = 团队不存在)与成员身份(is_member)。
	selectTeamMembership = `SELECT (tm.team_id IS NOT NULL) AS is_member FROM teams t LEFT JOIN team_members tm ON tm.team_id = t.id AND tm.user_id = $2 WHERE t.id = $1`
)

// ErrProjectNotFound 查询不到项目时返回。
var ErrProjectNotFound = errors.New("project not found")

// Project 对应 projects 表一行。Description/TeamID 为 nil 表示库中为 NULL。
type Project struct {
	ID          string
	Name        string
	Description *string
	Level       string
	TeamID      *string
	CreatedBy   string
	CreatedAt   time.Time
}

// Projects 提供 projects 表的数据访问与团队成员身份判定。
type Projects struct {
	db *sql.DB
}

// NewProjects 创建 Projects。
func NewProjects(db *sql.DB) *Projects { return &Projects{db: db} }

// scanProject 扫描一行 projects 数据,description/team_id 为 NULL 时置 nil。
func scanProject(s rowScanner) (Project, error) {
	var p Project
	var desc, teamID sql.NullString
	if err := s.Scan(&p.ID, &p.Name, &desc, &p.Level, &teamID, &p.CreatedBy, &p.CreatedAt); err != nil {
		return Project{}, err
	}
	if desc.Valid {
		p.Description = &desc.String
	}
	if teamID.Valid {
		p.TeamID = &teamID.String
	}
	return p, nil
}

// Create 插入新项目并返回完整行。teamID 为 nil 时落个人项目(team_id 为 NULL)。
// 成员身份校验由 handler 在调用前完成。
func (s *Projects) Create(ctx context.Context, name, description, level string, teamID *string, createdBy string) (Project, error) {
	// 简介为空串时落 NULL(projects.description 可空)。
	var desc any
	if description != "" {
		desc = description
	}
	var team any
	if teamID != nil {
		team = *teamID
	}

	p, err := scanProject(s.db.QueryRowContext(ctx, insertProject, name, desc, level, team, createdBy))
	if err != nil {
		return Project{}, fmt.Errorf("insert project %q: %w", name, err)
	}
	return p, nil
}

// ListPersonal 返回用户创建的个人项目列表(team_id IS NULL),按创建时间倒序(id 兜底)。
func (s *Projects) ListPersonal(ctx context.Context, userID string) ([]Project, error) {
	rows, err := s.db.QueryContext(ctx, selectProjectsByUser, userID)
	if err != nil {
		return nil, fmt.Errorf("list personal projects: %w", err)
	}
	defer rows.Close()

	projects := make([]Project, 0)
	for rows.Next() {
		p, err := scanProject(rows)
		if err != nil {
			return nil, fmt.Errorf("scan project: %w", err)
		}
		projects = append(projects, p)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate projects: %w", err)
	}
	return projects, nil
}

// ListByTeam 返回团队的全部项目,按创建时间倒序(id 兜底)。
func (s *Projects) ListByTeam(ctx context.Context, teamID string) ([]Project, error) {
	rows, err := s.db.QueryContext(ctx, selectProjectsByTeam, teamID)
	if err != nil {
		return nil, fmt.Errorf("list team projects: %w", err)
	}
	defer rows.Close()

	projects := make([]Project, 0)
	for rows.Next() {
		p, err := scanProject(rows)
		if err != nil {
			return nil, fmt.Errorf("scan project: %w", err)
		}
		projects = append(projects, p)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate projects: %w", err)
	}
	return projects, nil
}

// Get 按 id 查询项目,不存在时返回 ErrProjectNotFound。
func (s *Projects) Get(ctx context.Context, id string) (Project, error) {
	p, err := scanProject(s.db.QueryRowContext(ctx, selectProjectByID, id))
	if errors.Is(err, sql.ErrNoRows) {
		return Project{}, ErrProjectNotFound
	}
	if err != nil {
		return Project{}, fmt.Errorf("select project by id %q: %w", id, err)
	}
	return p, nil
}

// IsMember 判定用户是否为团队成员,同时校验团队存在性。
// 团队不存在返回 ErrTeamNotFound;团队存在时返回成员身份(bool),
// 供项目接口区分 404(团队不存在)与 403(非成员)。
func (s *Projects) IsMember(ctx context.Context, teamID, userID string) (bool, error) {
	var member bool
	err := s.db.QueryRowContext(ctx, selectTeamMembership, teamID, userID).Scan(&member)
	if errors.Is(err, sql.ErrNoRows) {
		return false, ErrTeamNotFound
	}
	if err != nil {
		return false, fmt.Errorf("check membership of team %s: %w", teamID, err)
	}
	return member, nil
}
