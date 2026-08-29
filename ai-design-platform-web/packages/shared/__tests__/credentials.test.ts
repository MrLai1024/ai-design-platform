import { beforeEach, describe, expect, it, vi } from 'vitest';
import { credentials } from '../src/utils/credentials';
import { createLocalStorageMock } from './helpers/local-storage';

const sample = { account: 'user_abc123', password: 'p@ssw0rd', token: 'jwt-token-1' };

beforeEach(() => {
  vi.stubGlobal('localStorage', createLocalStorageMock());
});

describe('credentials storage', () => {
  it('stores credentials under ai_design_account key (ai_design_ prefix)', () => {
    credentials.set(sample);
    expect(localStorage.getItem('ai_design_account')).toBe(JSON.stringify(sample));
  });

  it('reads back stored credentials', () => {
    credentials.set(sample);
    expect(credentials.get()).toEqual(sample);
  });

  it('returns null when nothing is stored', () => {
    expect(credentials.get()).toBeNull();
  });

  it('returns null when stored value is malformed', () => {
    localStorage.setItem('ai_design_account', JSON.stringify({ account: 'a', password: 123 }));
    expect(credentials.get()).toBeNull();

    localStorage.setItem('ai_design_account', 'not-json');
    expect(credentials.get()).toBeNull();
  });

  it('has() reflects whether valid credentials exist', () => {
    expect(credentials.has()).toBe(false);
    credentials.set(sample);
    expect(credentials.has()).toBe(true);
    credentials.remove();
    expect(credentials.has()).toBe(false);
  });

  it('getToken() returns token or null', () => {
    expect(credentials.getToken()).toBeNull();
    credentials.set(sample);
    expect(credentials.getToken()).toBe('jwt-token-1');
  });

  it('works when methods are destructured (no this dependency)', () => {
    const { get, set, has, getToken, remove } = credentials;
    expect(has()).toBe(false);
    expect(get()).toBeNull();
    set(sample);
    expect(has()).toBe(true);
    expect(get()).toEqual(sample);
    expect(getToken()).toBe('jwt-token-1');
    remove();
    expect(get()).toBeNull();
  });

  it('remove() clears the stored credentials', () => {
    credentials.set(sample);
    credentials.remove();
    expect(localStorage.getItem('ai_design_account')).toBeNull();
    expect(credentials.get()).toBeNull();
  });
});
