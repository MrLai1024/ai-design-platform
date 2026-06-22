/** Global event names used for cross-app communication */
export const GLOBAL_EVENTS = {
  /** User info changed (login, logout, profile update) */
  USER_CHANGED: 'user:changed',
  /** Tenant / workspace switched */
  TENANT_CHANGED: 'tenant:changed',
  /** Auth token expired — redirect to login */
  AUTH_UNAUTHORIZED: 'auth:unauthorized',
  /** Theme changed (light/dark) */
  THEME_CHANGED: 'theme:changed',
} as const;
