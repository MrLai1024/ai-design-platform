import { beforeEach, describe, expect, it, vi } from 'vitest';
import { http } from '../src/api/request';
import { installCaptureAdapter } from './helpers/http';
import { createLocalStorageMock } from './helpers/local-storage';

function setAccount(token: string) {
  localStorage.setItem(
    'ai_design_account',
    JSON.stringify({ account: 'user_1', password: 'pwd', token }),
  );
}

// Capture the default adapter once at module load so each test starts from the
// same baseline regardless of execution order.
const DEFAULT_ADAPTER = http.defaults.adapter;

beforeEach(() => {
  // Unstub every global (localStorage, window, ...) stubbed by any previous test.
  vi.unstubAllGlobals();
  vi.stubGlobal('localStorage', createLocalStorageMock());
  // Restore the adapter so tests that replace it never leak into later tests.
  http.defaults.adapter = DEFAULT_ADAPTER;
});

describe('request token injection', () => {
  it('injects Authorization Bearer header from credentials token on GET', async () => {
    setAccount('jwt-1');
    const { calls, adapter } = installCaptureAdapter();
    http.defaults.adapter = adapter;
    await http.get('/v1/teams');
    expect(calls[0].headers.Authorization).toBe('Bearer jwt-1');
  });

  it('injects Authorization Bearer header from credentials token on POST', async () => {
    setAccount('jwt-2');
    const { calls, adapter } = installCaptureAdapter();
    http.defaults.adapter = adapter;
    await http.post('/v1/projects', { name: 'p' });
    expect(calls[0].headers.Authorization).toBe('Bearer jwt-2');
  });

  it('omits Authorization header when no credentials exist', async () => {
    const { calls, adapter } = installCaptureAdapter();
    http.defaults.adapter = adapter;
    await http.get('/v1/teams');
    expect(calls[0].headers.Authorization).toBeUndefined();
  });

  it('falls back to legacy ai_design_token raw key', async () => {
    localStorage.setItem('ai_design_token', 'legacy-jwt');
    const { calls, adapter } = installCaptureAdapter();
    http.defaults.adapter = adapter;
    await http.get('/v1/teams');
    expect(calls[0].headers.Authorization).toBe('Bearer legacy-jwt');
  });

  it('prefers credentials token over legacy key', async () => {
    setAccount('new-jwt');
    localStorage.setItem('ai_design_token', 'legacy-jwt');
    const { calls, adapter } = installCaptureAdapter();
    http.defaults.adapter = adapter;
    await http.get('/v1/teams');
    expect(calls[0].headers.Authorization).toBe('Bearer new-jwt');
  });

  it('clears credentials and dispatches auth:unauthorized on 401', async () => {
    setAccount('jwt-3');
    localStorage.setItem('ai_design_token', 'legacy');
    const dispatchEvent = vi.fn();
    vi.stubGlobal('window', { dispatchEvent });
    http.defaults.adapter = () => Promise.reject({ response: { status: 401 } });
    await expect(http.get('/v1/teams')).rejects.toBeTruthy();
    expect(localStorage.getItem('ai_design_account')).toBeNull();
    expect(localStorage.getItem('ai_design_token')).toBeNull();
    expect(dispatchEvent).toHaveBeenCalledOnce();
  });
});
