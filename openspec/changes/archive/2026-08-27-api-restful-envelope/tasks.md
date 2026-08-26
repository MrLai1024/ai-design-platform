# 实施任务

> 本 change 为归档记录:全部任务已在代码与主 specs 中完成,此处按实施顺序记录。

## 1. RESTful 路由改造

- [x] 1.1 project-service newRouter 重排:POST /users 公开 + 组内其余认证(usersGroup 子组结构);GET /users/me/teams、GET /users/me/projects 挂 List;GET /teams 挂 Search;POST /teams/:id/members 挂 Join;移除旧路由(GET /teams 列表、/teams/search、/:id/join、GET /projects 列表)
- [x] 1.2 handler 调整:注册 200→201;Search keyword 可选(空 keyword 返回全部可加入,经 store `%%` ILIKE)
- [x] 1.3 gateway 反代前缀 /api/v1/auth → /api/v1/users
- [x] 1.4 测试:main_test 401/非 UUID 清单更新、TestAutoRegisterPublic、端到端流 201;auth/team/project handler 测试 URL 与断言更新;proxy_test 覆盖更新(/users 应代理、/auth 不再代理)

## 2. 统一信封格式

- [x] 2.1 新增 internal/handler/response.go:Success/Error helper + 码表常量(0/40000/40001/40100/40300/40400/40900/50000)
- [x] 2.2 auth/team/project 全部 handler 信封化(成功 data、错误 code+中文 msg+data null);errors.go internalError 改 50000;middleware 401 改 40100 信封(字面量+注释)
- [x] 2.3 测试断言全部改信封(auth/team/project/middleware/main 共 71 用例)

## 3. 前端适配

- [x] 3.1 request.ts 拦截器:code===0 → 返回 data;错误携带 message=msg/apiCode/response;401 逻辑保留;非信封透传
- [x] 3.2 user/team/project API 路径更新(函数签名不变,消费方零改动)
- [x] 3.3 TeamJoinModal 优先展示服务端 msg(apiCode 标记),409 回退本地文案
- [x] 3.4 测试:request 6 信封用例、user-api/useAccount/app 契约断言、teamJoinModal msg 用例

## 4. 验证与文档

- [x] 4.1 project-service 7 包全绿 + gateway 测试全绿
- [x] 4.2 E2E 冒烟(经 gateway):注册 code:0 三要素、重复加入 40900"已加入该团队"、无 token 40100"未认证"、列表 data 数组
- [x] 4.3 主 specs(user-account/project-space)同步端点与信封需求;openspec validate --specs 通过
