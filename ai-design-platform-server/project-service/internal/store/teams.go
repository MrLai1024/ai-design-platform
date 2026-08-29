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
	insertTeam           = `INSERT INTO teams (name, description, owner_id) VALUES ($1, $2, $3) RETURNING id, name, description, owner_id, created_at`
	insertTeamMember     = `INSERT INTO team_members (team_id, user_id) VALUES ($1, $2)`
	joinTeamMember       = `INSERT INTO team_members (team_id, user_id) SELECT t.id, $2 FROM teams t WHERE t.id = $1`
	selectTeamsByUser    = `SELECT t.id, t.name, t.description, t.owner_id, t.created_at FROM teams t JOIN team_members tm ON tm.team_id = t.id WHERE tm.user_id = $1 ORDER BY tm.joined_at DESC, t.created_at DESC, t.id DESC`
	selectTeamsByKeyword = `SELECT t.id, t.name, t.description, t.owner_id, t.created_at FROM teams t WHERE t.name ILIKE $1 AND NOT EXISTS (SELECT 1 FROM team_members tm WHERE tm.team_id = t.id AND tm.user_id = $2) ORDER BY t.created_at DESC, t.id DESC`
)

var (
	// ErrTeamNotFound 团队不存在时返回。
	ErrTeamNotFound = errors.New("team not found")
	// ErrMemberConflict 已是团队成员(唯一约束冲突)时返回。
	ErrMemberConflict = errors.New("already a member")
)

// Team 对应 teams 表一行。Description 为 nil 表示库中为 NULL。
type Team struct {
	ID          string
	Name        string
	Description *string
	OwnerID     string
	CreatedAt   time.Time
}

// Teams 提供 teams / team_members 表的数据访问。
type Teams struct {
	db *sql.DB
}

// NewTeams 创建 Teams。
func NewTeams(db *sql.DB) *Teams { return &Teams{db: db} }

// rowScanner 抽象 *sql.Row 与 *sql.Rows 共有的 Scan 方法。
type rowScanner interface {
	Scan(dest ...any) error
}

// scanTeam 扫描一行 teams 数据,description 为 NULL 时 Description 置 nil。
func scanTeam(s rowScanner) (Team, error) {
	var t Team
	var desc sql.NullString
	if err := s.Scan(&t.ID, &t.Name, &desc, &t.OwnerID, &t.CreatedAt); err != nil {
		return Team{}, err
	}
	if desc.Valid {
		t.Description = &desc.String
	}
	return t, nil
}

// ListByUser 返回用户已加入的团队,按加入时间倒序(创建时间、id 倒序兜底)。
func (s *Teams) ListByUser(ctx context.Context, userID string) ([]Team, error) {
	rows, err := s.db.QueryContext(ctx, selectTeamsByUser, userID)
	if err != nil {
		return nil, fmt.Errorf("list teams by user: %w", err)
	}
	defer rows.Close()

	teams := make([]Team, 0)
	for rows.Next() {
		t, err := scanTeam(rows)
		if err != nil {
			return nil, fmt.Errorf("scan team: %w", err)
		}
		teams = append(teams, t)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate teams: %w", err)
	}
	return teams, nil
}

// SearchByName 按名称模糊匹配团队(ILIKE),排除用户已加入的团队,按创建时间倒序(id 倒序兜底)。
func (s *Teams) SearchByName(ctx context.Context, keyword, userID string) ([]Team, error) {
	rows, err := s.db.QueryContext(ctx, selectTeamsByKeyword, "%"+keyword+"%", userID)
	if err != nil {
		return nil, fmt.Errorf("search teams by keyword %q: %w", keyword, err)
	}
	defer rows.Close()

	teams := make([]Team, 0)
	for rows.Next() {
		t, err := scanTeam(rows)
		if err != nil {
			return nil, fmt.Errorf("scan team: %w", err)
		}
		teams = append(teams, t)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate teams: %w", err)
	}
	return teams, nil
}

// CreateTeam 单事务创建团队并把创建者写入 team_members,任一步失败即回滚。
func (s *Teams) CreateTeam(ctx context.Context, name, description, ownerID string) (Team, error) {
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return Team{}, fmt.Errorf("begin create team: %w", err)
	}
	// 提交成功后 Rollback 是 no-op,错误可忽略。
	defer tx.Rollback() //nolint:errcheck

	// 描述为空串时落 NULL(teams.description 可空)。
	var desc any
	if description != "" {
		desc = description
	}

	t, err := scanTeam(tx.QueryRowContext(ctx, insertTeam, name, desc, ownerID))
	if err != nil {
		return Team{}, fmt.Errorf("insert team %q: %w", name, err)
	}
	if _, err := tx.ExecContext(ctx, insertTeamMember, t.ID, ownerID); err != nil {
		return Team{}, fmt.Errorf("insert creator member: %w", err)
	}
	if err := tx.Commit(); err != nil {
		return Team{}, fmt.Errorf("commit create team %q: %w", name, err)
	}
	return t, nil
}

// JoinTeam 写入团队成员。已加入返回 ErrMemberConflict,团队不存在返回 ErrTeamNotFound。
// 用 INSERT...SELECT 一次完成"团队存在性判定 + 写入",0 行受影响即团队不存在,
// 不依赖外键错误码判定,避免与 user_id 外键冲突混淆。
func (s *Teams) JoinTeam(ctx context.Context, teamID, userID string) error {
	res, err := s.db.ExecContext(ctx, joinTeamMember, teamID, userID)
	if err != nil {
		var pgErr *pgconn.PgError
		if errors.As(err, &pgErr) && pgErr.Code == "23505" {
			return fmt.Errorf("%w: team %s", ErrMemberConflict, teamID)
		}
		return fmt.Errorf("join team %s: %w", teamID, err)
	}
	n, err := res.RowsAffected()
	if err != nil {
		return fmt.Errorf("join team %s rows affected: %w", teamID, err)
	}
	if n == 0 {
		return fmt.Errorf("%w: team %s", ErrTeamNotFound, teamID)
	}
	return nil
}
