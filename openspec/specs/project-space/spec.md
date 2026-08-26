# project-space Specification

## Purpose

定义"项目空间"子应用:个人项目、团队项目两大板块,支持新建项目、创建团队、搜索并加入团队、查看项目详情;子应用采用菜单栏 + 面包屑导航,UI 使用 ant-design-vue。同时定义后端 project-service 微服务的团队/成员/项目接口与数据库表。

## Requirements

### Requirement: 项目空间子应用注册与导航

系统 SHALL 新增子应用 `project-space-app`,挂载在 `/project-space` 路由下,基座头部导航新增"项目空间"入口;子应用内部使用左侧菜单栏(个人项目/团队项目)与顶部面包屑导航。

#### Scenario: 基座导航含项目空间入口

- **WHEN** 平台加载完成
- **THEN** 基座头部导航包含"项目空间"入口,点击后跳转 `/project-space` 并加载子应用

#### Scenario: 子应用菜单栏

- **WHEN** 进入项目空间子应用
- **THEN** 左侧菜单栏展示"个人项目"、"团队项目"两个菜单项,可点击切换对应页面

#### Scenario: 面包屑逐级导航

- **WHEN** 用户依次进入 个人项目 → 某项目详情
- **THEN** 子应用头部面包屑展示 `首页 / 项目空间 / 个人项目 / <项目名>`,点击任一级可跳转对应路由

#### Scenario: 团队项目面包屑多一层级

- **WHEN** 用户依次进入 团队项目 → 某团队 → 某项目详情
- **THEN** 面包屑展示 `首页 / 项目空间 / 团队项目 / <团队名> / <项目名>`

### Requirement: 个人项目列表与空态

系统 SHALL 在个人项目页展示当前用户创建的个人项目列表;若不存在任何个人项目,则展示空态并提供新建项目入口。

#### Scenario: 存在个人项目时展示列表

- **WHEN** 当前用户存在个人项目
- **THEN** 个人项目页展示项目列表,列表项至少包含项目名称,点击列表项进入项目详情

#### Scenario: 无个人项目时展示空态

- **WHEN** 当前用户不存在任何个人项目
- **THEN** 个人项目页展示空态提示与"新建项目"按钮

### Requirement: 新建项目弹窗

系统 SHALL 提供新建项目弹窗,表单字段为:项目名称(必填)、项目简介(选填)、项目级别(单选框:演示级/生产级,必填)。

#### Scenario: 弹窗字段与默认值

- **WHEN** 用户点击新建项目按钮
- **THEN** 弹出弹窗,包含项目名称输入框、项目简介输入框、项目级别单选框(演示级/生产级,默认演示级),确认与取消按钮

#### Scenario: 校验与提交

- **WHEN** 用户未填写项目名称直接确认
- **THEN** 弹窗内提示项目名称必填,不发起提交

#### Scenario: 创建成功

- **WHEN** 用户完整填写表单并确认
- **THEN** 调用项目创建接口,成功后关闭弹窗并刷新当前列表,新项目出现在列表中

### Requirement: 项目详情菜单留白

系统 SHALL 提供项目详情页,包含 Issue、代码仓两个菜单项,菜单内容本期留白(占位)。

#### Scenario: 详情页菜单结构

- **WHEN** 用户点击任一项目进入项目详情
- **THEN** 详情页展示 Issue、代码仓两个菜单/tab,可切换,两个菜单内容区均为占位状态

### Requirement: 团队列表与创建团队

系统 SHALL 在团队项目页展示当前用户已加入的团队列表;提供创建团队入口(团队名称必填),创建成功后创建者自动成为团队成员。

#### Scenario: 展示已加入的团队

- **WHEN** 用户进入团队项目页且已加入至少一个团队
- **THEN** 展示团队列表,点击某团队进入该团队的项目列表页

#### Scenario: 创建团队

- **WHEN** 用户点击创建团队并填写团队名称确认
- **THEN** 调用团队创建接口,成功后新团队出现在团队列表中

#### Scenario: 未加入任何团队的空态

- **WHEN** 用户未加入任何团队
- **THEN** 团队项目页展示空态,提供"创建团队"与"加入团队"入口

### Requirement: 搜索并加入团队

系统 SHALL 提供加入团队功能:按团队名称搜索,展示搜索结果,用户点击加入后直接成为团队成员(无审批)。

#### Scenario: 按名称搜索团队

- **WHEN** 用户在加入团队弹窗输入关键字搜索
- **THEN** 展示名称匹配的团队列表(不含用户已加入的团队)

#### Scenario: 直接加入成功

- **WHEN** 用户点击某搜索结果团队的"加入"按钮
- **THEN** 调用加入接口,成功后该团队出现在我的团队列表中

#### Scenario: 重复加入被拦截

- **WHEN** 用户尝试加入已加入的团队
- **THEN** 接口拒绝,返回 409 或友好提示,不产生重复成员记录

### Requirement: 团队项目列表与项目详情

系统 SHALL 在团队内提供项目列表,团队成员可查看并新建团队项目;点击团队项目进入项目详情(与个人项目详情一致)。

#### Scenario: 团队项目列表

- **WHEN** 用户点击某个已加入的团队
- **THEN** 展示该团队的项目列表(空态含新建项目入口),列表项点击进入项目详情

#### Scenario: 新建团队项目归属团队

- **WHEN** 用户在团队内新建项目并提交
- **THEN** 项目创建接口以团队归属落库,新项目仅在该团队项目列表中展示

### Requirement: 项目接口

project-service SHALL 提供项目创建与列表接口:创建接口字段为名称、简介、级别、归属(个人或团队);列表接口按用户视角返回个人项目或指定团队项目。

#### Scenario: 创建个人项目

- **WHEN** 携带 token 请求 `POST /api/v1/projects`,体含名称/简介/级别且不含 team_id
- **THEN** 返回 201,项目落库 `team_id` 为空,created_by 为当前用户

#### Scenario: 创建团队项目

- **WHEN** 当前用户为团队成员,请求体含 team_id
- **THEN** 项目落库 `team_id` 为指定团队;非团队成员请求时返回 403

#### Scenario: 查询个人项目列表

- **WHEN** 携带 token 请求 `GET /api/v1/users/me/projects`
- **THEN** 返回当前用户创建且 `team_id` 为空的全部项目

#### Scenario: 查询团队项目列表

- **WHEN** 当前用户为团队成员,请求 `GET /api/v1/teams/:id/projects`
- **THEN** 返回该团队全部项目;非团队成员返回 403

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

### Requirement: 数据库表设计

project-service SHALL 使用 PostgreSQL 持久化,建表:users(账号/密码/时间戳)、teams(名称/简介/owner/时间戳)、team_members(团队-成员唯一关系/加入时间)、projects(名称/简介/级别/team_id 可空/创建人/时间戳);个人项目以 team_id 为空表示。

#### Scenario: 表结构与唯一约束

- **WHEN** project-service 启动执行迁移
- **THEN** 四张表创建成功:users.account 唯一;team_members(team_id, user_id) 唯一;projects.level 仅允许 demo/production 两类值

#### Scenario: 数据按用户隔离

- **WHEN** 用户 A 与用户 B 分别查询个人项目列表
- **THEN** 各自只看到自己创建的项目,互不可见
