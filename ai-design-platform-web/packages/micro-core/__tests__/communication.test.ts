import { describe, it, expect, vi } from 'vitest';

// Mock qiankun globals before importing the module
vi.mock('qiankun', () => {
  const listeners: Array<(state: unknown, prevState: unknown) => void> = [];
  const state: Record<string, unknown> = {};
  return {
    initGlobalState: vi.fn((initialState: unknown) => {
      Object.assign(state, initialState as Record<string, unknown>);
      return {
        onGlobalStateChange: vi.fn(
          (callback: (state: unknown, prevState: unknown) => void, fireImmediately?: boolean) => {
            listeners.push(callback);
            if (fireImmediately) {
              callback({ ...state }, { ...state });
            }
          },
        ),
        setGlobalState: vi.fn((newState: Record<string, unknown>) => {
          const prev = { ...state };
          Object.assign(state, newState);
          listeners.forEach((cb) => cb({ ...state }, prev));
        }),
        offGlobalStateChange: vi.fn(() => {
          listeners.length = 0;
        }),
      };
    }),
  };
});

import {
  initCommunication,
  onGlobalStateChange,
  setGlobalState,
  offGlobalStateChange,
} from '../src/communication';

describe('communication module', () => {
  it('initCommunication should set initialized flag', () => {
    expect(() => initCommunication()).not.toThrow();
    expect(() => initCommunication()).not.toThrow();
  });

  it('onGlobalStateChange should register a callback without throwing', () => {
    const callback = vi.fn();
    expect(() => onGlobalStateChange(callback, false)).not.toThrow();
  });

  it('setGlobalState should notify listeners', () => {
    const callback = vi.fn();
    onGlobalStateChange(callback, false);
    setGlobalState({ user: { id: '1', name: 'Test' } });
    expect(callback).toHaveBeenCalled();
  });
});
