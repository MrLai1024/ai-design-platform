import { reactive } from 'vue';
import { credentials, autoRegister } from '@ai-design/shared';
import type { AccountCredentials } from '@ai-design/shared';

export type AccountStatus = 'idle' | 'registering' | 'ready' | 'error';

export interface AccountState {
  status: AccountStatus;
  account: string | null;
  password: string | null;
  error: string | null;
}

export interface UseAccountOptions {
  /** Override the registration API (tests); defaults to shared autoRegister */
  register?: () => Promise<AccountCredentials>;
}

const REGISTER_ERROR_MESSAGE = '自动注册失败,请稍后重试';

/**
 * 基座账号状态(首次进入自动注册流程):
 * 无本地凭证 → 调用注册接口并写入 localStorage;已有凭证 → 直接使用;
 * 注册失败 → error 状态(不阻塞平台其他功能,可重试)。
 */
export function useAccount(options: UseAccountOptions = {}) {
  const register: () => Promise<AccountCredentials> = options.register ?? autoRegister;

  const state = reactive<AccountState>({
    status: 'idle',
    account: null,
    password: null,
    error: null,
  });

  function apply(value: AccountCredentials): void {
    state.account = value.account;
    state.password = value.password;
    state.status = 'ready';
    state.error = null;
  }

  /** 初始化账号:已有凭证直接使用,否则自动注册并持久化;失败进入 error 状态 */
  async function init(): Promise<void> {
    // Only guard against a concurrent in-flight registration. A 'ready' state
    // is intentionally NOT guarded: idempotency comes from the credentials
    // check below, so init() can still recover after a 401 wiped the stored
    // credentials while the state was 'ready'.
    if (state.status === 'registering') return;

    const existing = credentials.get();
    if (existing) {
      apply(existing);
      return;
    }

    state.status = 'registering';
    state.error = null;
    try {
      const created = await register();
      credentials.set(created);
      apply(created);
    } catch {
      state.status = 'error';
      state.error = REGISTER_ERROR_MESSAGE;
    }
  }

  /** 关闭失败提示(回到 idle,可再次 init 重试) */
  function dismissError(): void {
    if (state.status === 'error') {
      state.status = 'idle';
      state.error = null;
    }
  }

  /**
   * 凭证失效恢复:401 后拦截器已清除本地凭证并派发 AUTH_UNAUTHORIZED,
   * 清掉旧账号显示并重新自动注册;失败仍走 error 状态兜底。
   */
  function refreshCredentials(): Promise<void> {
    state.account = null;
    state.password = null;
    state.error = null;
    state.status = 'idle';
    return init();
  }

  return { state, init, dismissError, refreshCredentials };
}
