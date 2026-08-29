import { APP_NAMES, APP_ROUTES } from '@ai-design/shared';

export interface AppConfig {
  name: string;
  entry: string;
  container: string;
  activeRule: string;
  props?: Record<string, unknown>;
}

const ENTRY_MAP: Record<string, { dev: string; prod: string }> = {
  [APP_NAMES.AI_GENERATION]: {
    dev: '//localhost:8002',
    prod: '//cdn.example.com/ai-generation-app',
  },
  [APP_NAMES.PROJECT_SPACE]: {
    dev: '//localhost:8004',
    prod: '//cdn.example.com/project-space-app',
  },
};

/** Determine if running in dev mode based on globalThis */
function isDevMode(): boolean {
  if (
    typeof globalThis !== 'undefined' &&
    (globalThis as Record<string, unknown>).__DEV__ !== undefined
  ) {
    return !!(globalThis as Record<string, unknown>).__DEV__;
  }
  // webpack defines process.env.NODE_ENV at build time
  try {
    return (globalThis as Record<string, unknown>).process === undefined
      ? true
      : (globalThis as unknown as { process: { env: { NODE_ENV: string } } }).process.env
          .NODE_ENV === 'development';
  } catch {
    return true;
  }
}

/** Build the sub-app registration config list */
export function getAppConfigs(): AppConfig[] {
  const isDev = isDevMode();

  return [
    {
      name: APP_NAMES.AI_GENERATION,
      entry: isDev
        ? ENTRY_MAP[APP_NAMES.AI_GENERATION].dev
        : ENTRY_MAP[APP_NAMES.AI_GENERATION].prod,
      container: '#sub-app-generation',
      activeRule: APP_ROUTES[APP_NAMES.AI_GENERATION],
    },
    {
      name: APP_NAMES.PROJECT_SPACE,
      entry: isDev
        ? ENTRY_MAP[APP_NAMES.PROJECT_SPACE].dev
        : ENTRY_MAP[APP_NAMES.PROJECT_SPACE].prod,
      container: '#sub-app-project-space',
      activeRule: APP_ROUTES[APP_NAMES.PROJECT_SPACE],
    },
  ];
}
