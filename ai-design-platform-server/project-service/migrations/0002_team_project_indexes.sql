-- 0002_team_project_indexes.sql
-- 二级索引:覆盖 teams / projects 的常见查询路径
-- (我的团队列表、团队项目列表、个人项目列表)。
-- 全部使用 IF NOT EXISTS,幂等;由启动迁移 runner 按文件名排序执行。

CREATE INDEX IF NOT EXISTS idx_team_members_user_id ON team_members (user_id);

CREATE INDEX IF NOT EXISTS idx_projects_team_id ON projects (team_id);

CREATE INDEX IF NOT EXISTS idx_projects_created_by ON projects (created_by) WHERE team_id IS NULL;

-- 预留:当前无按 owner 查询路径,提前建索引以备后续使用。
CREATE INDEX IF NOT EXISTS idx_teams_owner_id ON teams (owner_id);
