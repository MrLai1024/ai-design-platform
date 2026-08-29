import { beforeEach, describe, expect, it, vi } from 'vitest';
import { http } from '../src/api/request';
import { autoRegister, getMe } from '../src/api/user';
import { installCaptureAdapter } from './helpers/http';
import { createLocalStorageMock } from './helpers/local-storage';

const credentialsBody = { account: 'user_abc123', password: 'p@ssw0rd', token: 'jwt-token' };
const meBody = { account: 'user_abc123', password: 'p@ssw0rd' };

beforeEach(() => {
  vi.unstubAllGlobals();
  vi.stubGlobal('localStorage', createLocalStorageMock());
});

/**
 * Response body contract: the response interceptor unwraps the `{code, msg, data}`
 * envelope, so user APIs must resolve with the business payload itself — NOT an
 * AxiosResponse and NOT the envelope. If the envelope shape ever changes, these
 * exact-equality assertions fail and the mismatch is caught here instead of
 * silently corrupting stored credentials.
 */
describe('user api — response body contract', () => {
  it('autoRegister resolves with the unwrapped credentials payload', async () => {
    const { calls, adapter } = installCaptureAdapter({
      code: 0,
      msg: 'success',
      data: credentialsBody,
    });
    http.defaults.adapter = adapter;

    const result = await autoRegister();

    expect(result).toEqual(credentialsBody);
    expect(calls[0].method).toBe('post');
    expect(calls[0].url).toBe('/v1/users');
  });

  it('getMe resolves with the unwrapped account payload', async () => {
    const { calls, adapter } = installCaptureAdapter({ code: 0, msg: 'success', data: meBody });
    http.defaults.adapter = adapter;

    const result = await getMe();

    expect(result).toEqual(meBody);
    expect(calls[0].method).toBe('get');
    expect(calls[0].url).toBe('/v1/users/me');
  });
});
