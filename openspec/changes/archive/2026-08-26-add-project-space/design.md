# 设计:个人信息 + 项目空间

## Context

平台现状:

- 前端为 qiankun 微前端:基座 `main`(Vue3+TS+Tailwind)+ 3 个子应用(ai-chat-app :8001 / ai-generation-app :8002 / ai-workflow :8003),注册链为 `shared/app-names.ts` → `micro-core/apps-config.ts` → 基座 router + App.vue 容器。
- 后端 gateway(Go/gin :8080)是唯一 HTTP 入口;`middleware/auth.go` 是桩代码(所有用户为 anonymous);store 均为内存实现,`DATABASE_URL` 已配置但从未接线(PostgreSQL 仅存在于 docker-compose)。
- 已确认的产品取舍:账号密码轻量处理(明文存储、localStorage 保存、清缓存丢数据可接受、无找回功能);加入团队直接加入无审批;团队内不细分权限;创建团队功能本期包含。

## Goals / Non-Goals

**Goals:**

- 基座头部最右侧个人信息入口 + 自动账号分配/登录 + 账号密码查看弹窗。
- 新增 project-space-app 子应用(个人/团队项目、创建/搜索/加入团队、新建项目、项目详情留白 tab、面包屑)。
- 新增 project-service 微服务,首次接入 PostgreSQL,完成用户/团队/成员/项目持久化。
- gateway 以反向代理方式接入新服务,现有 AI 链路行为不变。

**Non-Goals:**

- 不做账号找回、不做真实注册/登录页、不做密码哈希(有意明文)。
- 不做团队审批、角色权限(仅区分"是否团队成员")。
- Issue、代码仓功能本体(仅菜单占位)。
- 不改造现有 AI 链路的数据隔离(conversations 仍为现状)。

## Decisions

### D1: 后端形态 —— 新增独立 Go 服务 project-service(HTTP),gateway 反向代理

**选择**:新建 `ai-design-platform-server/project-service`,Go + gin,暴露 HTTP,gateway 将 `/api/v1/auth`、`/api/v1/teams`、`/api/v1/projects` 路由组反向代理至该服务。

**备选**:
- *gateway 内直接加 handler + store*:改动最小,但违背"设计为微服务"的明确要求,且用户域与 AI 域耦合加深。
- *gRPC 服务(仿 ai-service)*:与现有多语言 gRPC 体系一致,但本项目为纯 CRUD,proto/buf 生成链路带来的成本大于收益,HTTP 更轻。

**理由**:gateway 已有转发下游服务的先例,新增服务边界清晰;HTTP 避免 proto 成本,契合"轻"的诉求。JWT 采用 HS256,由 project-service 签发并独占校验(密钥仅 project-service 持有,见 D7),gateway 对转发路由做纯反向代理、不做鉴权拦截(由 project-service 自行鉴权,见 tasks 5.2)。

### D2: 身份模型 —— 浏览器即身份,账号一次性

**选择**:首次进入(以 localStorage 中是否存在凭证判定)调用 `POST /auth/auto-register`,服务端生成 `user_` 前缀 + 随机串账号、随机密码,明文落 users 表,签发 JWT 返回;前端将 `{account, password, token}` 存 localStorage(`ai_design_` 前缀,复用 shared 的 storage 封装)。

**理由**:产品明确接受清缓存/换浏览器 = 新账号、旧数据不可找回。不做设备指纹(引入隐私复杂度,违背"轻")。密码明文存储是"个人信息弹窗可持续回显密码"的直接推论,已在 proposal 中标注为有意取舍。

### D3: 数据模型 —— 个人项目 = team_id IS NULL

**选择**:

```
users        id uuid pk / account varchar unique / password varchar / created_at
teams        id uuid pk / name varchar / description text / owner_id → users / created_at
team_members team_id → teams / user_id → users / joined_at, unique(team_id, user_id)
projects     id uuid pk / name varchar / description text / level enum('demo','production')
             team_id uuid null → teams / created_by → users / created_at
```

- 个人项目:`team_id IS NULL`;团队项目:`team_id` 非空。一个表承载两种归属,避免多态关联表。
- `level` 用 varchar + CHECK 约束(轻,免 pg enum 变更成本)。
- 权限规则:团队项目仅团队成员可见/可建;个人项目仅创建者可见。

### D4: 迁移机制 —— 启动时幂等执行内嵌 SQL

**选择**:project-service 启动时读取 `migrations/` 目录(embed)按序执行幂等 DDL(`CREATE TABLE IF NOT EXISTS` + 唯一索引),并维护 schema_migrations 记录表。

**备选**:golang-migrate/goose 独立迁移工具。本期仅 4 张表,引入外部迁移框架得不偿失;启动时自动迁移保证"起服务即建库",后续表多再切正式迁移工具。

### D5: 前端子应用 —— project-space-app,端口 8004,antd 只在子应用

**选择**:

- 新包 `packages/project-space-app`:webpack dev server :8004,注册链同现有三个子应用(新增 `APP_NAMES.PROJECT_SPACE = 'project-space-app'`、`APP_ROUTES` `/project-space`、apps-config 条目、基座路由 `/project-space/:pathMatch(.*)*`、App.vue 容器与导航项)。
- 子应用内部路由(自持 vue-router):
  - `/project-space` → 重定向 `/project-space/personal`
  - `/project-space/personal` 个人项目列表
  - `/project-space/teams` 我的团队列表(创建/搜索加入入口)
  - `/project-space/teams/:teamId` 团队项目列表
  - `/project-space/projects/:id` 项目详情(个人/团队共用,面包屑依据来源路由渲染;团队来源带 `?from=team&teamId=` 或由进入路径推导)
- UI:ant-design-vue 仅在 project-space-app 引入(按需引入 Sider/Menu/Breadcrumb/Modal/Form/Table 等);基座个人信息弹窗沿用 Tailwind 风格,不给基座引入 antd。qiankun 下 antd 样式隔离用 webpack 处理,子应用样式独立打包,不污染基座。
- **联调发现并已修复(2026-08-26)**:qiankun 2.10.16 的 `experimentalStyleIsolation` 实际是 scopedCSS 前缀改写(不创建 shadow DOM),所有样式被改写为 `div[data-qiankun="..."]` 前缀;antd Modal 等 Teleport 组件默认渲染到 document.body(在 wrapper 外),前缀规则无法命中 → 弹窗完全无样式。修复:新增 `src/portal-root.ts` 在 main.ts 挂载时记录真实挂载点(qiankun 下不能直接 `document.getElementById('app')`——那会命中基座的 #app),三个 Modal 组件传 `:get-container="getAppContainer"` 渲染进挂载点。**后续新增 Select/Tooltip/Popover/message 等 Teleport 组件时需同样处理(getPopupContainer/attachTo)。**

**理由**:详情页复用单一路由减少重复代码;面包屑由路由匹配表推导,天然支持"个人/团队"两种层级。

### D6: 接口清单

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/v1/auth/auto-register` | 自动注册,返回 account/password/token |
| GET | `/api/v1/auth/me` | 当前用户账号信息(含密码) |
| GET | `/api/v1/teams` | 我的团队列表 |
| GET | `/api/v1/teams/search?keyword=` | 按名称搜索(排除已加入) |
| POST | `/api/v1/teams` | 创建团队(创建者自动入成员) |
| POST | `/api/v1/teams/:id/join` | 加入团队(重复返回 409) |
| GET | `/api/v1/teams/:id/projects` | 团队项目列表(成员可见) |
| GET | `/api/v1/projects` | 个人项目列表(team_id IS NULL) |
| POST | `/api/v1/projects` | 创建项目(无 team_id=个人;有则校验成员身份,非成员 403) |
| GET | `/api/v1/projects/:id` | 项目详情(校验归属可见性) |

统一响应格式与错误码沿用 gateway 现有 handler 风格(`{"error": ...}`,HTTP 状态码语义化)。请求头 `Authorization: Bearer <token>`。

### D7: 部署与配置

- docker-compose 新增 `project-service` 服务(端口 8081 内部通信或直接暴露 8081 供 gateway 转发;开发模式本机直跑 `go run`)。
- 环境变量:`PROJECT_SERVICE_PORT`(服务端口,默认 8081)、`DATABASE_URL`(project-service 直连同一 postgres)、`JWT_SECRET`(仅 project-service 持有并校验)、`PROJECT_SERVICE_ADDR`(gateway 反向代理上游地址,默认 http://localhost:8081)。
- 前端 shared 包新增 `api/user.ts`、`api/team.ts`、`api/project.ts` 与 token 注入的 request 拦截器(现有 `shared/api/request.ts` 扩展)。

## Risks / Trade-offs

- **[明文密码 + localStorage 存凭证]** → 已确认为产品有意取舍;缓解:账号仅在本平台使用、token 设置合理有效期、后续可平滑迁移到哈希存储(加不可逆迁移路径)。
- **[清缓存丢数据]** → 孤儿数据留在库中无害;缓解:后续可做"账号找回"或合并入口,本期明确不做。
- **[gateway 反向代理引入延迟与故障点]** → 仅用户/项目域走转发,AI 链路直连不受影响;project-service 不可用时返回 502,前端全局错误提示。
- **[首次接入 PostgreSQL 的迁移风险]** → 迁移幂等 + 启动自检;postgres 已在 compose 中就绪,风险低。
- **[antd-vue 与 qiankun 样式冲突]** → 子应用独立 webpack 构建 + CSS 局部作用域,按需引入组件;若冲突难以收敛,退化方案为子应用内用 scoped Tailwind 仿 antd 风格(保底)。
- **[JWT 密钥管理]** → 单机部署场景,环境变量共享密钥即可;密钥轮换机制后续再说。

## Migration Plan

1. 后端先行:project-service 建表迁移 → 接口 → gateway 代理路由 → docker-compose。
2. 前端:shared 常量/API 封装 → 基座个人信息 + token 注入 → project-space-app 骨架 → 各页面。
3. 部署:新增服务容器随 compose 一键起,postgres 无既有表冲突(全新库,无历史数据迁移负担)。
4. 回滚:git revert 即可;数据库为新增表,无需回滚脚本(可手工 DROP 新表)。

## Open Questions

- 无(账号找回、审批、角色等已明确划出本期范围)。
