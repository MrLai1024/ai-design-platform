import { initGlobalState, type OnGlobalStateChangeCallback } from 'qiankun';
import type { GlobalState } from '@ai-design/shared';

const initialState: GlobalState = {};

const actions = initGlobalState(initialState);

let initialized = false;

/** Initialize communication. Called once by register.ts. */
export function initCommunication(): void {
  if (initialized) return;
  initialized = true;
}

/**
 * Listen for global state changes.
 * @param callback — called on every state change
 * @param fireImmediately — if true, callback fires with current state immediately
 */
export function onGlobalStateChange(
  callback: (state: GlobalState, prevState: GlobalState) => void,
  fireImmediately = false,
): void {
  actions.onGlobalStateChange(callback as OnGlobalStateChangeCallback, fireImmediately);
}

/**
 * Update global state — notifies all sub-apps.
 */
export function setGlobalState(state: Partial<GlobalState>): void {
  actions.setGlobalState(state as Record<string, unknown>);
}

/**
 * Remove all global state listeners.
 */
export function offGlobalStateChange(): void {
  actions.offGlobalStateChange();
}
