import { get, post } from './request';
import type { AccountCredentials, CurrentUser } from '../types/account';

/**
 * 自动注册:首次进入平台时调用,后端生成唯一账号与随机密码并签发 JWT
 * POST /api/v1/auth/auto-register → { account, password, token }
 * (响应拦截器已解包 response.data,Promise 直接解析为响应体)
 */
export function autoRegister(): Promise<AccountCredentials> {
  return post<AccountCredentials>('/v1/auth/auto-register');
}

/**
 * 查询当前登录用户账号信息(含密码,供个人信息弹窗回显)
 * GET /api/v1/auth/me → { account, password }
 * (响应拦截器已解包 response.data,Promise 直接解析为响应体)
 */
export function getMe(): Promise<CurrentUser> {
  return get<CurrentUser>('/v1/auth/me');
}
