# 接口规范统一:RESTful 资源化 + 统一信封格式

## Why

平台用户域接口最初混用了动词式路径(`/teams/search`、`/teams/:id/join`)与动作式认证端点(`/auth/auto-register`、`/auth/me`),且各接口响应格式不统一(裸数据与 `{"error": ...}` 混杂),前端需要针对每个接口分别处理。本次变更将用户域接口统一为 RESTful 资源风格,并规定统一响应信封格式,建立前后端契约的单一规范。

## What Changes

- **RESTful 资源化**(旧路径彻底移除,无别名):
  - `POST /users` — 自动注册(原 `/auth/auto-register`),公开
  - `GET /users/me` — 当前用户信息(原 `/auth/me`)
  - `GET /users/me/teams` — 我的团队列表(原 `GET /teams`)
  - `GET /teams?keyword=` — 可加入团队列表/搜索(原 `/teams/search`,keyword 可选、始终排除已加入)
  - `POST /teams/:id/members` — 加入团队(原 `/teams/:id/join`)
  - `GET /users/me/projects` — 我的个人项目列表(原 `GET /projects`)
  - 保留:`POST /teams`、`GET /teams/:id/projects`、`POST /projects`、`GET /projects/:id`
- **统一响应信封** `{code, msg, data}`:
  - 成功:`{code: 0, msg: "success", data: <业务数据>}`(无业务数据时 data 为 null)
  - 错误:`{code: <业务码>, msg: "<中文提示>", data: null}`,HTTP 状态码保留语义化
  - 业务码表:0 成功 / 40000 参数错误 / 40001 用户不存在 / 40100 未认证 / 40300 无权限 / 40400 资源不存在 / 40900 冲突 / 50000 内部错误
  - 前端请求层解包 data 返回业务数据本体(函数类型零改动),错误携带 `apiCode` + 中文 `msg` 供界面展示(优先服务端提示,回退本地文案)
- 主 specs(`user-account`、`project-space`)已同步端点与信封需求。

## Capabilities

### New Capabilities

(无)

### Modified Capabilities

- `user-account`:认证端点资源化(`/users`、`/users/me`),新增统一响应信封格式需求(含业务码表与前端解包约定)。
- `project-space`:团队/项目端点资源化(我的团队、搜索、加入、个人项目列表),响应格式随信封统一。

## Impact

- **后端**:project-service 路由与 handler 重排(公开/认证子组结构)、新增 `internal/handler/response.go`(Success/Error helper + 码表)、auth 中间件 401 信封化;gateway 反代前缀 `/api/v1/auth` → `/api/v1/users`;全部 handler/中间件测试断言更新为信封。
- **前端**:shared 的 request.ts 拦截器解包信封(成功返回 data、错误带 apiCode/msg、401 逻辑保留、非信封透传兼容)、user/team/project API 路径更新(函数签名不变,消费方零改动)、TeamJoinModal 优先展示服务端 msg;相关测试适配。
- **文档**:主 specs 两个 capability 的端点与信封需求已同步。
