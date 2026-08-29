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
    http.defaults.adapter = () =>
      Promise.reject({ response: { status: 401, data: { code: 40100, msg: '未认证', data: null } } });
    const err = await http.get('/v1/teams').catch((e) => e);
    expect(err.message).toBe('未认证');
    expect(localStorage.getItem('ai_design_account')).toBeNull();
    expect(localStorage.getItem('ai_design_token')).toBeNull();
    expect(dispatchEvent).toHaveBeenCalledOnce();
  });
});

describe('response envelope unwrapping', () => {
  it('unwraps {code: 0, msg, data} to the business payload', async () => {
    const payload = { id: 'p1', name: '设计' };
    const { adapter } = installCaptureAdapter({ code: 0, msg: 'success', data: payload });
    http.defaults.adapter = adapter;
    await expect(http.get('/v1/projects')).resolves.toEqual(payload);
  });

  it('resolves null for success envelopes without a payload (join etc.)', async () => {
    const { adapter } = installCaptureAdapter({ code: 0, msg: 'success', data: null });
    http.defaults.adapter = adapter;
    await expect(http.post('/v1/teams/team-1/members')).resolves.toBeNull();
  });

  it('rejects with the server msg on a 2xx response whose code !== 0', async () => {
    const { adapter } = installCaptureAdapter({ code: 40000, msg: '参数错误', data: null });
    http.defaults.adapter = adapter;
    const err = await http.get('/v1/teams').catch((e) => e);
    expect(err.message).toBe('参数错误');
    expect(err.apiCode).toBe(40000);
    expect(err.response.status).toBe(200);
  });

  it('rejects with the server msg and keeps the HTTP status on a 409', async () => {
    http.defaults.adapter = () =>
      Promise.reject({
        response: { status: 409, data: { code: 40900, msg: '已加入该团队', data: null } },
      });
    const err = await http.get('/v1/teams').catch((e) => e);
    expect(err.response.status).toBe(409);
    expect(err.message).toBe('已加入该团队');
    expect(err.apiCode).toBe(40900);
  });

  it('rejects with the server msg on HTTP errors with an envelope body', async () => {
    http.defaults.adapter = () =>
      Promise.reject({
        response: { status: 500, data: { code: 50000, msg: '内部错误', data: null } },
      });
    const err = await http.get('/v1/teams').catch((e) => e);
    expect(err.response.status).toBe(500);
    expect(err.message).toBe('内部错误');
    expect(err.apiCode).toBe(50000);
  });

  it('passes non-envelope bodies through unchanged (migration fallback)', async () => {
    const raw = { items: [1, 2] };
    const { adapter } = installCaptureAdapter(raw);
    http.defaults.adapter = adapter;
    await expect(http.get('/v1/legacy')).resolves.toEqual(raw);
  });
});
