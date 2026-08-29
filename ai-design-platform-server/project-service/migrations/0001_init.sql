-- 0001_init.sql
-- 初始表结构:users / teams / team_members / projects。
-- 全部使用 IF NOT EXISTS,幂等;由启动迁移 runner 按文件名排序执行。

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS users (
    id         uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    account    varchar(255) NOT NULL UNIQUE,
    password   varchar(255) NOT NULL,
    created_at timestamptz  NOT NULL DEFAULT now()
);

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
