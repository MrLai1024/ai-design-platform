# user-account Specification

## Purpose

平台轻量账号体系的接口规范变更:认证端点资源化(RESTful)与统一响应信封格式。主 spec 已同步(本 delta 记录变更本身)。

## MODIFIED Requirements

### Requirement: 首次进入自动分配账号并自动登录

用户首次进入平台时,系统 SHALL 自动调用后端注册接口分配账号与密码,签发登录凭证,并自动完成登录,全程无需用户输入任何信息。

#### Scenario: 首次进入自动注册

- **WHEN** 浏览器本地存储中不存在账号凭证,用户首次打开平台
- **THEN** 前端自动调用 `POST /api/v1/users` 接口,后端生成唯一账号与随机密码并持久化,返回 201 与账号、密码、JWT token

### Requirement: 自动注册接口

后端 SHALL 提供自动注册接口:生成随机账号与随机密码并持久化到 users 表,签发 JWT token 返回。账号在系统内唯一,密码为可逆存储以满足回显需求。

#### Scenario: 注册成功返回三要素

- **WHEN** 服务端收到 `POST /api/v1/users` 请求
- **THEN** 返回 201,响应体包含 `account`、`password`、`token` 字段,账号格式与密码复杂度满足既定规则

### Requirement: 账号信息查询接口

后端 SHALL 提供当前登录用户账号信息查询接口,返回账号与密码。

#### Scenario: 查询本人账号信息

- **WHEN** 携带有效 token 请求 `GET /api/v1/users/me`
- **THEN** 返回 200,响应体包含 `account`、`password` 字段

#### Scenario: 未登录查询被拒绝

- **WHEN** 未携带有效 token 请求 `GET /api/v1/users/me`
- **THEN** 返回 401

## ADDED Requirements

### Requirement: 统一响应信封格式

平台所有接口 SHALL 返回统一信封格式:成功 `{"code": 0, "msg": "success", "data": <业务数据>}`,错误 `{"code": <业务码>, "msg": "<中文提示>", "data": null}`;HTTP 状态码保留语义化(200/201/400/401/403/404/409/500)。业务码:0 成功、40000 参数错误、40001 用户不存在、40100 未认证、40300 无权限、40400 资源不存在、40900 冲突、50000 内部错误。前端请求层 SHALL 解包 data 返回业务数据本体,错误时携带服务端 msg 供界面展示。

#### Scenario: 成功响应解包

- **WHEN** 接口返回 `{"code":0,"msg":"success","data":{...}}`
- **THEN** 前端请求层返回 `data` 本体,业务代码直接使用,无需处理信封

#### Scenario: 错误响应携带业务码与提示

- **WHEN** 接口返回错误信封(如 `{"code":40900,"msg":"已加入该团队","data":null}`)
- **THEN** 前端收到带 `apiCode` 与中文 `msg` 的错误,界面可展示服务端提示;HTTP 状态码仍保留(409 等)
