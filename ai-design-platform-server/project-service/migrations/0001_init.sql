-- 0001_init.sql
-- 初始表结构:teams / team_members / projects(业务表)。
-- users 表由 gateway(全局服务)在启动时创建,本迁移仅保留对 users 的外键引用,
-- 因此 project-service 必须晚于 gateway 启动(compose 已约束 depends_on)。
-- pgcrypto 扩展保留:业务表主键仍依赖 gen_random_uuid()。
-- 全部使用 IF NOT EXISTS,幂等;由启动迁移 runner 按文件名排序执行。

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS teams (
    id          uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    name        varchar(255) NOT NULL,
    description text,
    owner_id    uuid         NOT NULL REFERENCES users (id),
    created_at  timestamptz  NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS team_members (
    team_id   uuid        NOT NULL REFERENCES teams (id),
    user_id   uuid        NOT NULL REFERENCES users (id),
    joined_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (team_id, user_id)
);

CREATE TABLE IF NOT EXISTS projects (
    id          uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    name        varchar(255) NOT NULL,
    description text,
    level       varchar(16)  NOT NULL CHECK (level IN ('demo', 'production')),
    team_id     uuid         REFERENCES teams (id),
    created_by  uuid         NOT NULL REFERENCES users (id),
    created_at  timestamptz  NOT NULL DEFAULT now()
);
