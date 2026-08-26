# 设计:接口规范统一(RESTful + 信封)

## Context

add-project-space 交付后的接口存在三类不一致:动词式路径(`/teams/search`、`/teams/:id/join`)、动作式认证端点(`/auth/auto-register`、`/auth/me`)、混杂响应格式(裸数据与 `{"error":...}`)。本次变更在既有实现上做契约规范统一,前后端同批切换。

## Goals / Non-Goals

**Goals:**
- 用户域接口全量 RESTful 资源化,旧路径彻底移除(无别名,避免双契约)
- 统一响应信封 `{code, msg, data}`,HTTP 状态码保留语义化
- 前端改造对业务代码零侵入(函数签名与类型不变,消费方零改动)

**Non-Goals:**
- 不改 AI 链路(chat/conversation/generation)接口与 SSE(仍走原生 fetch,不涉及信封)
- 不做分页/过滤等新能力,仅契约规范化
- 不引入 OpenAPI 文档生成

## Decisions

### D1: 资源化端点设计

用户资源化与"我的"子资源:
- `POST /users`(公开,创建用户=自动注册,201)
- `GET /users/me`(当前用户)
- `GET /users/me/teams`(我的团队)
- `GET /users/me/projects`(我的个人项目)
- `GET /teams?keyword=`(可加入团队列表,keyword 可选过滤、始终排除已加入;空 keyword 返回全部可加入,不再 400)
- `POST /teams/:id/members`(加入 = 创建成员资源,409 冲突)
- 保留资源:`POST /teams`、`GET /teams/:id/projects`、`POST /projects`、`GET /projects/:id`

**理由**:`/users/me/*` 子资源是"当前用户上下文"的 RESTful 惯例,避免 `GET /teams` 语义歧义(我的 vs 全部);搜索本质是列表过滤,归入 `GET /teams`;加入是创建成员资源。备选(保留 `/auth/*` 惯例、`/teams/search` 动词)被否:用户明确要求全量 RESTful。

### D2: 统一信封与业务码

- 成功 `{code:0, msg:"success", data}`;无业务数据(join 等)data 为 null
- 错误 `{code, msg, data:null}`,msg 为中文(如"已加入该团队")
- 码表:0 / 40000 参数错误 / 40001 用户不存在 / 40100 未认证 / 40300 无权限 / 40400 资源不存在 / 40900 冲突 / 50000 内部错误
- **HTTP 状态码保留**(RESTful 语义),信封只做 body 规范化;前端错误识别可同时用 HTTP 状态与业务码
- 实现:`internal/handler/response.go` 包级 Success/Error helper + 码表常量;auth 中间件 401 用字面量 40100(避免 handler↔middleware import 环,注释说明)

### D3: 前端解包与错误携带

- 响应拦截器:信封 `code===0` → 返回 `data` 本体(业务代码类型零改动);2xx 但 code≠0 或 HTTP 非 2xx 均抛错,错误对象带 `message=服务端 msg`、`apiCode=业务码`、`response`(保留 HTTP 状态)
- 401 行为保留(清凭证 + 派发 AUTH_UNAUTHORIZED)
- 非信封响应原样透传(迁移过渡期兜底)
- 消费方:优先展示服务端 msg(带 apiCode 标记才用,避免 axios 网络错误文案泄漏),无则回退本地文案

### D4: 兼容与迁移

- 旧路径彻底移除、无别名(前后端同批切换,无外部消费者)
- gateway 反代前缀 `/api/v1/auth` → `/api/v1/users`(透传 body 不受信封影响)

## Risks / Trade-offs

- [业务码表为内部约定,未来扩展需保持向后兼容] → 码表常量集中,新增码只增不改
- [middleware 码表字面量重复] → 已注释;如需单源后续抽 `internal/httpx` 小包
- [错误 msg 统一"参数错误"损失字段级提示] → 码表契约下可后续细分 msg,code 不变
- [拦截器对非信封透传为过渡兜底] → 全量信封化后可将透传分支标记废弃

## Migration Plan

已完成(本次为归档记录):后端 response.go + handler/中间件改造 → gateway 前缀 → 前端拦截器/API 路径 → 测试 → E2E 冒烟 → 主 specs 同步。

## Open Questions

- 无(HTTP 状态码保留、码表、解包行为均已定案)
