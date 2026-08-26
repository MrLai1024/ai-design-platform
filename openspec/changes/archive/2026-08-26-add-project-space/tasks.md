# 实施任务

## 1. project-service 骨架与数据库

- [x] 1.1 创建 `ai-design-platform-server/project-service` 目录结构(cmd/server、internal/config|store|handler|middleware、migrations),go.mod 初始化,复用 gateway 的 gin 依赖版本
- [x] 1.2 实现 config 加载(DATABASE_URL、JWT_SECRET、PROJECT_SERVICE_PORT 环境变量,带默认值;端口变量名定为 PROJECT_SERVICE_PORT 以避免与 gateway 的 SERVER_PORT 冲突)
- [x] 1.3 实现 PostgreSQL 连接池初始化与启动自检(ping 失败即退出)
- [x] 1.4 实现启动时幂等迁移:embed `migrations/` SQL,建 users/teams/team_members/projects 四张表及唯一约束(users.account 唯一、team_members(team_id,user_id) 唯一、projects.level CHECK 约束),维护 schema_migrations 记录
- [x] 1.5 编写迁移 SQL 文件(0001_init.sql)

## 2. 用户认证接口

- [x] 2.1 实现 JWT 签发/校验工具(HS256,共享 JWT_SECRET,user_id 进 claims,过期时间 7 天)
- [x] 2.2 实现 `POST /api/v1/auth/auto-register`:生成 `user_` 前缀唯一账号 + 随机密码,明文落 users 表,返回 {account, password, token};并发冲突时重试换账号
- [x] 2.3 实现 `GET /api/v1/auth/me`:解析 token 返回当前用户 account/password
- [x] 2.4 实现认证中间件:无 token/无效 token 返回 401;解析 user_id 注入 context
- [x] 2.5 为用户/团队/项目路由组挂载认证中间件,health 路由豁免

## 3. 团队接口

- [x] 3.1 实现 `GET /api/v1/teams`:查询当前用户已加入的团队列表
- [x] 3.2 实现 `POST /api/v1/teams`:创建团队(名称必填),创建者自动写入 team_members
- [x] 3.3 实现 `GET /api/v1/teams/search?keyword=`:按名称模糊匹配,排除当前用户已加入的团队
- [x] 3.4 实现 `POST /api/v1/teams/:id/join`:写入 team_members;重复加入返回 409

## 4. 项目接口

- [x] 4.1 实现 `POST /api/v1/projects`:创建项目(名称必填/简介选填/level 必填);无 team_id 落个人项目;有 team_id 时校验成员身份,非成员返回 403
- [x] 4.2 实现 `GET /api/v1/projects`:返回当前用户创建的个人项目列表(team_id IS NULL)
- [x] 4.3 实现 `GET /api/v1/teams/:id/projects`:返回团队项目列表,非团队成员返回 403
- [x] 4.4 实现 `GET /api/v1/projects/:id`:项目详情,校验归属可见性(个人项目仅创建者、团队项目仅成员)

## 5. gateway 接入与部署

- [x] 5.1 gateway 新增反向代理:将 `/api/v1/auth`、`/api/v1/teams`、`/api/v1/projects` 转发至 project-service(httputil.ReverseProxy),上游地址走环境变量 PROJECT_SERVICE_ADDR
- [x] 5.2 gateway auth 中间件调整:仅对现有 AI 链路路由保持现状行为,转发路由不拦截(由 project-service 自行鉴权)
- [x] 5.3 docker-compose 新增 project-service 服务定义(依赖 postgres,共享 DATABASE_URL/JWT_SECRET)
- [ ] 5.4 本机跑通:docker compose up 后自动注册/创建团队/创建项目接口全链路可用(可用 curl 验证)

## 6. 前端 shared 包

- [x] 6.1 `constants/app-names.ts` 新增 `PROJECT_SPACE: 'project-space-app'` 与 `APP_ROUTES` `/project-space`
- [x] 6.2 `api/request.ts` 扩展:从 localStorage 读取 token 注入 `Authorization: Bearer` 头
- [x] 6.3 新增 `api/user.ts`(autoRegister、getMe)、`api/team.ts`(list/create/search/join)、`api/project.ts`(create/list/teamList/detail),类型定义入 `types/`
- [x] 6.4 新增账号凭证的 storage 封装(读写 {account, password, token},沿用 `ai_design_` 前缀)

## 7. 基座个人信息

- [x] 7.1 App.vue 头部导航最右侧新增个人信息入口(展示账号名或默认头像,位于所有菜单项之后)
- [x] 7.2 实现首次进入自动注册逻辑:无本地凭证时调用 autoRegister,成功写入 localStorage;已有凭证直接使用
- [x] 7.3 实现个人信息弹窗:展示账号、密码,可关闭(基座 Tailwind 风格)
- [x] 7.4 注册接口失败时的兜底:页面提示错误,不阻塞平台其他功能使用

## 8. project-space-app 子应用骨架

- [x] 8.1 创建 `packages/project-space-app`(webpack 配置、tsconfig、package.json、端口 8004),注册进 micro-core apps-config、基座 router、App.vue 容器与导航菜单
- [x] 8.2 引入 ant-design-vue 并按需引入(Menu/Sider/Breadcrumb/Modal/Form/Table/Tag 等),配置子应用独立样式打包
- [x] 8.3 子应用 router:五条路由(personal、teams、teams/:teamId、projects/:id、默认重定向到 personal)
- [x] 8.4 布局组件:左侧 Menu(个人项目/团队项目)+ 顶部面包屑(由路由匹配表推导,个人/团队两种层级)
- [x] 8.5 面包屑"首页"与各级点击跳转(首页回基座 `/`,`项目空间` 回 `/project-space/personal`)

## 9. 子应用页面

- [x] 9.1 个人项目页:项目列表(名称/级别 Tag/简介),空态展示"新建项目"按钮
- [x] 9.2 新建项目弹窗:名称(必填)/简介(选填)/级别单选框(演示级默认、生产级),表单校验,提交成功关闭并刷新列表
- [x] 9.3 团队项目页:我的团队列表(空态:创建团队 + 加入团队两个入口)
- [x] 9.4 创建团队弹窗:团队名称必填,创建成功后刷新团队列表
- [x] 9.5 加入团队弹窗:关键字搜索,结果列表带"加入"按钮(已加入的团队不展示),加入成功后刷新我的团队
- [x] 9.6 团队项目列表页(teams/:teamId):展示该团队项目,含新建项目(带 team_id)入口
- [x] 9.7 项目详情页(projects/:id):Issue/代码仓两个 tab(内容占位),面包屑按来源层级渲染

## 10. 联调与验证

- [ ] 10.1 全链路手工验证:首次进入自动注册 → 头部弹窗看账号密码 → 建个人项目 → 建团队 → 搜索加入 → 团队建项目 → 进详情看 tab(后端链路已 curl 全量验证;浏览器 UI 走查待用户本地执行)
- [x] 10.2 异常路径验证:清 localStorage 重新注册、重复加入团队 409 提示、非团队成员访问团队项目 403(API 级实测 409/403/401/404 全过;清 localStorage 重新注册由 useAccount 单测覆盖;浏览器级提示由组件测试覆盖)
- [x] 10.3 前端单测:面包屑层级推导、注册/凭证读写逻辑(shared 与子应用关键组件)(shared 50/project-space-app 76/main 20/micro-core 7 全绿)
- [x] 10.4 后端测试:auth/team/project handler 的接口测试(httptest),迁移幂等性验证(重复启动不报错)(7 包全绿 + 活库重启验证迁移跳过、schema_migrations 无重复)
- [x] 10.5 按 CLAUDE.md 流程完成代码评审与验证后交付(用户自行 git 提交)(各组两阶段审查 + 最终整体审查 READY_TO_MERGE,I1 已修复)
