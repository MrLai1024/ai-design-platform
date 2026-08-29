import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useAccount } from '../src/composables/useAccount';
import { http } from '@ai-design/shared';
import type { AccountCredentials } from '@ai-design/shared';
import { installCaptureAdapter } from '../../shared/__tests__/helpers/http';

const sample: AccountCredentials = {
  account: 'user_abc123',
  password: 'p@ssw0rd',
  token: 'jwt-token-1',
};

function storedCredentials(): AccountCredentials {
  const raw = localStorage.getItem('ai_design_account');
  expect(raw).not.toBeNull();
  return JSON.parse(raw as string) as AccountCredentials;
}

beforeEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe('useAccount', () => {
  it('registers and persists credentials on first visit (no local credentials)', async () => {
    const register = vi.fn().mockResolvedValue(sample);
    const { state, init } = useAccount({ register });

    expect(state.status).toBe('idle');
    await init();

    expect(register).toHaveBeenCalledOnce();
    expect(storedCredentials()).toEqual(sample);
    expect(state.status).toBe('ready');
    expect(state.account).toBe('user_abc123');
    expect(state.password).toBe('p@ssw0rd');
    expect(state.error).toBeNull();
  });

  it('reuses existing credentials without calling register', async () => {
    localStorage.setItem('ai_design_account', JSON.stringify(sample));
    const register = vi.fn().mockResolvedValue(sample);
    const { state, init } = useAccount({ register });

    await init();

    expect(register).not.toHaveBeenCalled();
    expect(state.status).toBe('ready');
    expect(state.account).toBe('user_abc123');
    expect(state.password).toBe('p@ssw0rd');
  });

  it('enters error state when registration fails, without blocking anything', async () => {
    const register = vi.fn().mockRejectedValue(new Error('network down'));
    const { state, init } = useAccount({ register });

    await init();

    expect(register).toHaveBeenCalledOnce();
    expect(state.status).toBe('error');
    expect(state.account).toBeNull();
    expect(state.error).toBeTruthy();
    expect(localStorage.getItem('ai_design_account')).toBeNull();
  });

  it('dismissError clears the error state back to idle', async () => {
    const register = vi.fn().mockRejectedValue(new Error('network down'));
    const { state, init, dismissError } = useAccount({ register });

    await init();
    expect(state.status).toBe('error');

    dismissError();
    expect(state.status).toBe('idle');
    expect(state.error).toBeNull();
  });

  it('retries registration after a failure', async () => {
    const register = vi
      .fn()
      .mockRejectedValueOnce(new Error('network down'))
      .mockResolvedValueOnce(sample);
    const { state, init } = useAccount({ register });

    await init();
    expect(state.status).toBe('error');

    await init();
    expect(register).toHaveBeenCalledTimes(2);
    expect(state.status).toBe('ready');
    expect(state.account).toBe('user_abc123');
    expect(storedCredentials()).toEqual(sample);
  });

  it('calls register only once for concurrent init calls', async () => {
    let resolveRegister!: (value: AccountCredentials) => void;
    const register = vi.fn(
      () =>
        new Promise<AccountCredentials>((resolve) => {
          resolveRegister = resolve;
        }),
    );
    const { state, init } = useAccount({ register });

    const first = init();
    const second = init();
    expect(register).toHaveBeenCalledTimes(1);

    resolveRegister(sample);
    await first;
    await second;
    expect(state.status).toBe('ready');
    expect(register).toHaveBeenCalledTimes(1);
  });

  it('recovers via init() when credentials are wiped while ready (401 cleared storage)', async () => {
    localStorage.setItem('ai_design_account', JSON.stringify(sample));
    const register = vi
      .fn()
      .mockResolvedValue({ ...sample, account: 'user_new999', token: 'jwt-new' });
    const { state, init } = useAccount({ register });

    await init();
    expect(state.status).toBe('ready');
    expect(state.account).toBe('user_abc123');

    // Simulate the 401 interceptor clearing stored credentials while state stays 'ready'
    localStorage.removeItem('ai_design_account');

    await init();
    expect(register).toHaveBeenCalledTimes(1);
    expect(state.status).toBe('ready');
    expect(state.account).toBe('user_new999');
    expect(storedCredentials().account).toBe('user_new999');
  });

  it('refreshCredentials resets the visible account and re-registers after a 401', async () => {
    localStorage.setItem('ai_design_account', JSON.stringify(sample));
    const register = vi
      .fn()
      .mockResolvedValue({ ...sample, account: 'user_new999', token: 'jwt-new' });
    const { state, init, refreshCredentials } = useAccount({ register });

    await init();
    expect(state.account).toBe('user_abc123');

    // 401 flow: the interceptor wipes credentials before the event fires
    localStorage.removeItem('ai_design_account');

    await refreshCredentials();

    expect(register).toHaveBeenCalledTimes(1);
    expect(state.status).toBe('ready');
    expect(state.account).toBe('user_new999');
    expect(storedCredentials().account).toBe('user_new999');
  });

  it('registers through the real autoRegister API and persists the unwrapped body', async () => {
    // No injected register: exercise the default path (shared autoRegister →
    // real http instance → response interceptor) with a mocked adapter
    // resolving the {code, msg, data} envelope.
    const { calls, adapter } = installCaptureAdapter({
      code: 0,
      msg: 'success',
      data: sample,
    });
    http.defaults.adapter = adapter;
    const { state, init } = useAccount();

    await init();

    expect(state.status).toBe('ready');
    expect(state.account).toBe('user_abc123');
    expect(calls[0].url).toBe('/v1/users');
    // The interceptor must unwrap the envelope: if it ever leaked the envelope
    // (or an AxiosResponse) through, the persisted value fails the credentials
    // shape check and this round-trip assertion catches the mismatch instead
    // of silently re-registering later.
    expect(storedCredentials()).toEqual(sample);
    http.defaults.adapter = undefined;
  });
});
