# 个人信息 + 项目空间

## Why

平台目前没有用户体系(auth 中间件为桩代码,所有请求均为 anonymous),也没有任何持久化(store 全内存)。用户既无法感知自己的身份,也无法拥有属于自己的项目数据。本次变更引入轻量自动账号体系,并新增"项目空间"子应用,让用户可以管理个人/团队项目,为后续 Issue、代码仓等协作能力打地基。

## What Changes

- 基座应用头部导航栏最右侧新增个人信息入口:首次进入平台自动分配账号密码并自动登录,账号信息保存在浏览器 localStorage;点击入口弹窗展示账号、密码等信息。
- 新增子应用 `project-space-app`(Vue3 + TS + ant-design-vue),包含:
  - 个人项目:项目列表(空态引导新建)、新建项目弹窗(项目名称、项目简介、项目级别"演示级/生产级"单选框)、进入项目详情。
  - 团队项目:我的团队列表;加入团队(按名称搜索,直接加入,无审批);创建团队;点击团队进入该团队项目列表;项目详情同个人项目。
  - 项目详情:Issue、代码仓 菜单栏,two 个菜单内容本期留白。
  - 子应用头部面包屑导航(首页 → 项目空间 → 个人项目/团队项目 → [团队名 →] 项目名),面包屑可点击跳转。
- 新增微服务 `project-service`(Go/gin,HTTP):用户自动注册、JWT 签发与校验、团队/成员/项目 CRUD,直连 PostgreSQL(平台首次接入真实数据库)。
- gateway 新增反向代理路由组,将 `/api/v1/auth`、`/api/v1/teams`、`/api/v1/projects` 等转发至 project-service。
- 新增数据库表:`users`、`teams`、`team_members`、`projects`;个人项目以 `projects.team_id IS NULL` 表示。

## Capabilities

### New Capabilities

- `user-account`: 平台轻量账号体系 —— 首次进入自动分配账号密码并自动登录、账号信息存 localStorage、个人信息弹窗展示账号密码;后端自动注册接口、JWT 签发与校验、账号信息查询接口。
- `project-space`: 项目空间子应用 —— 个人项目/团队项目的列表与详情、新建项目、创建团队、搜索并加入团队、面包屑与菜单栏导航;后端 teams/projects/成员相关接口与数据库表。

### Modified Capabilities

(无 —— 现有 specs 均为 AI 生成链路相关,不涉及用户与项目域)

## Impact

- **前端**
  - 基座:App.vue 头部导航、个人信息系统(入口、弹窗、localStorage 读写)、请求拦截器携带 token。
  - 新增包 `packages/project-space-app`(webpack dev server,端口 8004)。
  - 注册链:`shared/src/constants/app-names.ts` → `micro-core/src/apps-config.ts` → 基座 router + App.vue 容器。
  - 新依赖:ant-design-vue(仅 project-space-app 使用)。
- **后端**
  - 新增服务 `ai-design-platform-server/project-service`(Go/gin,HTTP)。
  - gateway:新增反向代理路由组;auth 中间件接入 JWT 验签(仅对转发的用户/项目域路由生效,现有 AI 链路路由行为不变)。
  - 数据库:PostgreSQL 首次接入,新增 4 张表及迁移机制。
  - docker-compose 新增 project-service 服务定义。
- **安全取舍(有意为之)**:密码明文存储以便弹窗回显;localStorage 保存账号密码 token;清缓存/换浏览器 = 新账号,旧数据无法找回。本期不做找回功能。
