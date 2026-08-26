# user-account Specification

## Purpose

定义平台轻量账号体系:首次进入自动分配账号密码并自动登录,账号信息保存在浏览器本地存储,基座头部个人信息入口可查看账号密码。后端提供自动注册、JWT 签发/校验与账号信息查询接口。

## ADDED Requirements

### Requirement: 首次进入自动分配账号并自动登录

用户首次进入平台时,系统 SHALL 自动调用后端注册接口分配账号与密码,签发登录凭证,并自动完成登录,全程无需用户输入任何信息。

#### Scenario: 首次进入自动注册

- **WHEN** 浏览器本地存储中不存在账号凭证,用户首次打开平台
- **THEN** 前端自动调用 `POST /api/v1/auth/auto-register` 接口,后端生成唯一账号与随机密码并持久化,返回账号、密码与 JWT token

#### Scenario: 自动登录生效

- **WHEN** 自动注册接口返回成功
- **THEN** 前端将账号、密码、token 写入 localStorage,后续请求携带 token,用户无需手动登录即处于已登录状态

#### Scenario: 已注册用户不重复注册

- **WHEN** 浏览器本地存储中已存在账号凭证,用户再次进入平台
- **THEN** 前端不调用注册接口,直接使用本地 token 访问平台

### Requirement: 账号信息保存在浏览器本地存储

系统 SHALL 将自动分配得到的账号、密码与 token 保存在浏览器 localStorage 中(沿用 shared 包 `ai_design_` 前缀的 storage 封装)。

#### Scenario: 本地存储内容完整

- **WHEN** 自动注册成功后
- **THEN** localStorage 中存在账号、密码、token 三个字段,且字段值与接口返回一致

#### Scenario: 本地存储失效后重新走注册

- **WHEN** 用户清除浏览器缓存后再次进入平台
- **THEN** 系统视为首次进入,重新触发自动注册流程(旧账号数据本期无找回途径)

### Requirement: 个人信息入口展示账号密码

基座头部导航栏最右侧 SHALL 提供个人信息入口,点击后展示当前用户的账号与密码等信息。

#### Scenario: 头部最右侧展示个人信息入口

- **WHEN** 平台页面渲染完成且用户已登录
- **THEN** 头部导航栏最右侧展示个人信息入口(展示当前账号名或头像),入口位于所有导航菜单项之后

#### Scenario: 弹窗展示账号密码

- **WHEN** 用户点击个人信息入口
- **THEN** 弹出弹窗,展示账号与密码等信息,信息来源于本地存储;弹窗可关闭

### Requirement: 自动注册接口

后端 SHALL 提供自动注册接口:生成随机账号与随机密码并持久化到 users 表,签发 JWT token 返回。账号在系统内唯一,密码为可逆存储以满足回显需求。

#### Scenario: 注册成功返回三要素

- **WHEN** 服务端收到 `POST /api/v1/auth/auto-register` 请求
- **THEN** 返回 200,响应体包含 `account`、`password`、`token` 字段,账号格式与密码复杂度满足既定规则

#### Scenario: 账号唯一性

- **WHEN** 并发注册请求同时到达
- **THEN** 每个请求分配到的账号互不相同(唯一约束兜底)

### Requirement: JWT 签发与校验

project-service SHALL 签发 JWT token 并独占校验签名密钥,用户域接口凭 token 识别用户身份;token 无效或缺失时,用户域接口返回 401。

#### Scenario: 携带有效 token 访问用户域接口

- **WHEN** 请求携带有效的 JWT token 访问 `/api/v1/teams`、`/api/v1/projects` 等用户域接口
- **THEN** 接口正常返回该用户视角的数据

#### Scenario: 无 token 或 token 无效

- **WHEN** 请求未携带 token 或 token 签名校验失败
- **THEN** 接口返回 401,不返回任何业务数据

### Requirement: 账号信息查询接口

后端 SHALL 提供当前登录用户账号信息查询接口,返回账号与密码。

#### Scenario: 查询本人账号信息

- **WHEN** 携带有效 token 请求 `GET /api/v1/auth/me`
- **THEN** 返回 200,响应体包含 `account`、`password` 字段

#### Scenario: 未登录查询被拒绝

- **WHEN** 未携带有效 token 请求 `GET /api/v1/auth/me`
- **THEN** 返回 401
