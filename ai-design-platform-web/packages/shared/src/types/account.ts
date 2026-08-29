/**
 * 账号凭证 — 自动注册接口返回,并持久化到 localStorage(ai_design_account 键)。
 * 有意明文存储(轻量账号体系,个人信息弹窗需回显账号密码)。
 */
export interface AccountCredentials {
  account: string;
  password: string;
  token: string;
}

/** GET /api/v1/auth/me 响应 — 当前用户账号信息 */
export interface CurrentUser {
  account: string;
  password: string;
}
