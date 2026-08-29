# project-space Specification

## Purpose

项目空间接口的 RESTful 资源化变更。主 spec 已同步(本 delta 记录变更本身)。

## MODIFIED Requirements

### Requirement: 团队与成员接口

project-service SHALL 提供团队接口:我的团队列表、按名称搜索团队、创建团队、加入团队。

#### Scenario: 查询我的团队

- **WHEN** 携带 token 请求 `GET /api/v1/users/me/teams`
- **THEN** 返回当前用户已加入的全部团队

#### Scenario: 搜索团队

- **WHEN** 请求 `GET /api/v1/teams?keyword=<名称关键字>`
- **THEN** 返回名称匹配的团队列表,排除当前用户已加入的团队;不带 keyword 时返回全部可加入团队

#### Scenario: 加入团队

- **WHEN** 携带 token 请求 `POST /api/v1/teams/:id/members`
- **THEN** 当前用户成为该团队成员;重复加入返回 409

### Requirement: 项目接口

project-service SHALL 提供项目创建与列表接口:创建接口字段为名称、简介、级别、归属(个人或团队);列表接口按用户视角返回个人项目或指定团队项目。

#### Scenario: 查询个人项目列表

- **WHEN** 携带 token 请求 `GET /api/v1/users/me/projects`
- **THEN** 返回当前用户创建且 `team_id` 为空的全部项目
