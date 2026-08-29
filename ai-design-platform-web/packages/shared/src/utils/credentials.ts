import { storage } from './storage';
import type { AccountCredentials } from '../types/account';

/** storage 键名(实际 localStorage 键为 ai_design_account,由 storage 封装自动加前缀) */
const CREDENTIALS_KEY = 'account';

/**
 * 读取凭证;不存在或格式非法时返回 null(视同首次进入,需重新自动注册)。
 */
function get(): AccountCredentials | null {
  const value = storage.get<Partial<AccountCredentials>>(CREDENTIALS_KEY);
  if (
    value &&
    typeof value.account === 'string' &&
    typeof value.password === 'string' &&
    typeof value.token === 'string'
  ) {
    return { account: value.account, password: value.password, token: value.token };
  }
  return null;
}

/** 写入凭证 */
function set(value: AccountCredentials): void {
  storage.set(CREDENTIALS_KEY, value);
}

/** 是否存在有效凭证(用于判断是否首次进入) */
function has(): boolean {
  return get() !== null;
}

/** 读取 token,供请求拦截器注入 Authorization 头 */
function getToken(): string | null {
  return get()?.token ?? null;
}

/** 清除凭证 */
function remove(): void {
  storage.remove(CREDENTIALS_KEY);
}

/**
 * 账号凭证的本地存储封装。
 * 读写 { account, password, token } 于 localStorage 的 ai_design_account 键。
 * 无凭证或数据格式非法时 get() 返回 null(视同首次进入,需重新自动注册)。
 * 方法均为模块内函数(不依赖 this),可安全解构使用。
 */
export const credentials = { get, set, has, getToken, remove };
