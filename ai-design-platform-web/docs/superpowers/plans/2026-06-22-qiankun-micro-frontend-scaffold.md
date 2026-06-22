# Qiankun Micro-Frontend Scaffold Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scaffold a monorepo micro-frontend tech base with qiankun, pnpm workspace, Webpack 5, Vue3/React apps, Tailwind CSS, and full code standards toolchain.

**Architecture:** 4 apps (1 base + 3 sub-apps) under `apps/`, 2 shared packages under `packages/`. Base dispatches by route prefix; sub-apps manage internal routing. Cross-app communication via qiankun `initGlobalState` event bus.

**Tech Stack:** pnpm 8+, Webpack 5, TypeScript 5, Vue 3 + Pinia, React 18 + Redux Toolkit, qiankun, Tailwind CSS 3 + PostCSS, ESLint + Prettier + Husky + lint-staged + Commitlint

---

## Phase 1: Monorepo Foundation

### Task 1.1: Initialize root project

**Files:**

- Create: `package.json`
- Create: `pnpm-workspace.yaml`
- Create: `tsconfig.base.json`
- Create: `.gitignore`
- Create: `.npmrc`

- [ ] **Step 1: Create root package.json**

```json
{
  "name": "ai-design-platform",
  "private": true,
  "version": "0.0.0",
  "description": "AI Design Platform — Micro-Frontend Tech Base",
  "engines": {
    "node": ">=18",
    "pnpm": ">=8"
  },
  "scripts": {
    "dev": "pnpm -r --parallel dev",
    "dev:main": "pnpm --filter @ai-design/main dev",
    "dev:chat": "pnpm --filter @ai-design/ai-chat-app dev",
    "dev:generation": "pnpm --filter @ai-design/ai-generation-app dev",
    "dev:workflow": "pnpm --filter @ai-design/ai-workflow dev",
    "build": "pnpm -r build",
    "build:main": "pnpm --filter @ai-design/main build",
    "build:chat": "pnpm --filter @ai-design/ai-chat-app build",
    "build:generation": "pnpm --filter @ai-design/ai-generation-app build",
    "build:workflow": "pnpm --filter @ai-design/ai-workflow build",
    "lint": "pnpm -r lint",
    "format": "prettier --write \"**/*.{js,jsx,ts,tsx,vue,css,json,md}\"",
    "format:check": "prettier --check \"**/*.{js,jsx,ts,tsx,vue,css,json,md}\"",
    "prepare": "husky install",
    "clean": "pnpm -r exec rm -rf dist node_modules"
  },
  "devDependencies": {
    "@commitlint/cli": "^18.4.3",
    "@commitlint/config-conventional": "^18.4.3",
    "eslint": "^8.56.0",
    "husky": "^9.0.10",
    "lint-staged": "^15.2.0",
    "prettier": "^3.2.4",
    "typescript": "^5.3.3"
  }
}
```

- [ ] **Step 2: Create pnpm-workspace.yaml**

```yaml
packages:
  - 'apps/*'
  - 'packages/*'
```

- [ ] **Step 3: Create tsconfig.base.json**

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "module": "ESNext",
    "moduleResolution": "node",
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "jsx": "preserve",
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "forceConsistentCasingInFileNames": true,
    "resolveJsonModule": true,
    "allowSyntheticDefaultImports": true,
    "declaration": true,
    "declarationMap": true,
    "sourceMap": true,
    "baseUrl": ".",
    "paths": {
      "@ai-design/shared": ["packages/shared/src"],
      "@ai-design/shared/*": ["packages/shared/src/*"],
      "@ai-design/micro-core": ["packages/micro-core/src"],
      "@ai-design/micro-core/*": ["packages/micro-core/src/*"]
    }
  },
  "exclude": ["node_modules", "dist"]
}
```

- [ ] **Step 4: Create .gitignore**

```
node_modules/
dist/
.turbo/
*.log
.DS_Store
Thumbs.db
.env.local
.env.*.local
*.tsbuildinfo
```

- [ ] **Step 5: Create .npmrc**

```
shamefully-hoist=true
strict-peer-dependencies=false
```

- [ ] **Step 6: Install root dependencies and verify**

```bash
pnpm install
```

Expected: `pnpm install` completes without errors, root `node_modules` created.

- [ ] **Step 7: Initialize git and commit**

```bash
git init
git add package.json pnpm-workspace.yaml tsconfig.base.json .gitignore .npmrc pnpm-lock.yaml
git commit -m "chore: init monorepo foundation"
```

---

## Phase 2: Code Standards Toolchain

### Task 2.1: ESLint configuration

**Files:**

- Create: `.eslintrc.cjs`
- Create: `.eslintignore`

- [ ] **Step 1: Create .eslintrc.cjs**

```js
module.exports = {
  root: true,
  env: {
    browser: true,
    es2021: true,
    node: true,
  },
  extends: ['eslint:recommended'],
  parserOptions: {
    ecmaVersion: 'latest',
    sourceType: 'module',
  },
  ignorePatterns: ['dist', 'node_modules', '*.config.js', '*.config.cjs'],
  rules: {
    'no-console': 'warn',
    'no-debugger': 'warn',
    'no-unused-vars': ['warn', { argsIgnorePattern: '^_' }],
    'prefer-const': 'error',
    'no-var': 'error',
  },
  overrides: [
    {
      files: ['**/*.ts', '**/*.tsx'],
      parser: '@typescript-eslint/parser',
      extends: ['plugin:@typescript-eslint/recommended'],
      rules: {
        '@typescript-eslint/no-unused-vars': ['warn', { argsIgnorePattern: '^_' }],
        '@typescript-eslint/explicit-function-return-type': 'off',
        '@typescript-eslint/no-explicit-any': 'warn',
      },
    },
    {
      files: ['**/*.vue'],
      extends: ['plugin:vue/vue3-recommended'],
      parser: 'vue-eslint-parser',
      parserOptions: {
        parser: '@typescript-eslint/parser',
      },
      rules: {
        'vue/multi-word-component-names': 'off',
      },
    },
    {
      files: ['**/*.jsx', '**/*.tsx'],
      extends: ['plugin:react/recommended', 'plugin:react-hooks/recommended'],
      settings: {
        react: {
          version: 'detect',
        },
      },
      rules: {
        'react/react-in-jsx-scope': 'off',
      },
    },
  ],
};
```

- [ ] **Step 2: Create .eslintignore**

```
node_modules/
dist/
*.config.js
*.config.cjs
*.config.ts
```

- [ ] **Step 3: Install ESLint plugins**

```bash
pnpm add -D -w @typescript-eslint/parser @typescript-eslint/eslint-plugin eslint-plugin-vue eslint-plugin-react eslint-plugin-react-hooks vue-eslint-parser
```

- [ ] **Step 4: Commit**

```bash
git add .eslintrc.cjs .eslintignore package.json pnpm-lock.yaml
git commit -m "chore: add ESLint configuration"
```

### Task 2.2: Prettier configuration

**Files:**

- Create: `.prettierrc`
- Create: `.prettierignore`

- [ ] **Step 1: Create .prettierrc**

```json
{
  "semi": true,
  "singleQuote": true,
  "trailingComma": "all",
  "printWidth": 100,
  "tabWidth": 2,
  "useTabs": false,
  "bracketSpacing": true,
  "arrowParens": "always",
  "endOfLine": "lf",
  "vueIndentScriptAndStyle": false
}
```

- [ ] **Step 2: Create .prettierignore**

```
node_modules/
dist/
pnpm-lock.yaml
*.log
```

- [ ] **Step 3: Verify Prettier works**

```bash
npx prettier --check .eslintrc.cjs .prettierrc
```

Expected: Both files pass formatting check.

- [ ] **Step 4: Commit**

```bash
git add .prettierrc .prettierignore
git commit -m "chore: add Prettier configuration"
```

### Task 2.3: Husky + lint-staged + Commitlint

**Files:**

- Create: `.lintstagedrc.cjs`
- Create: `commitlint.config.cjs`
- Create: `.husky/pre-commit`
- Create: `.husky/commit-msg`

- [ ] **Step 1: Create .lintstagedrc.cjs**

```js
module.exports = {
  '*.{js,jsx,ts,tsx}': ['eslint --fix', 'prettier --write'],
  '*.vue': ['eslint --fix', 'prettier --write'],
  '*.{css,scss,less}': ['prettier --write'],
  '*.{json,md,yaml,yml}': ['prettier --write'],
};
```

- [ ] **Step 2: Create commitlint.config.cjs**

```js
module.exports = {
  extends: ['@commitlint/config-conventional'],
  rules: {
    'type-enum': [
      2,
      'always',
      ['feat', 'fix', 'refactor', 'style', 'docs', 'test', 'chore', 'perf', 'ci', 'build'],
    ],
    'subject-case': [0],
  },
};
```

- [ ] **Step 3: Initialize Husky**

```bash
npx husky install
```

Expected: `.husky/` directory created with `_/` contents.

- [ ] **Step 4: Create .husky/pre-commit**

```bash
#!/usr/bin/env sh
. "$(dirname -- "$0")/_/husky.sh"

npx lint-staged
```

- [ ] **Step 5: Create .husky/commit-msg**

```bash
#!/usr/bin/env sh
. "$(dirname -- "$0")/_/husky.sh"

npx --no -- commitlint --edit $1
```

- [ ] **Step 6: Make hooks executable and verify commitlint**

```bash
chmod +x .husky/pre-commit .husky/commit-msg
echo "foo" | npx commitlint
```

Expected: commitlint rejects "foo" as invalid. (Error is expected — verifying it rejects bad messages.)

- [ ] **Step 7: Commit**

```bash
git add .lintstagedrc.cjs commitlint.config.cjs .husky/ package.json
git commit -m "chore: add Husky, lint-staged, and Commitlint"
```

---

## Phase 3: Shared Packages

### Task 3.1: packages/shared

**Files:**

- Create: `packages/shared/package.json`
- Create: `packages/shared/tsconfig.json`
- Create: `packages/shared/src/index.ts`
- Create: `packages/shared/src/types/index.ts`
- Create: `packages/shared/src/types/global-state.ts`
- Create: `packages/shared/src/types/api.ts`
- Create: `packages/shared/src/utils/index.ts`
- Create: `packages/shared/src/utils/format.ts`
- Create: `packages/shared/src/utils/storage.ts`
- Create: `packages/shared/src/api/index.ts`
- Create: `packages/shared/src/api/request.ts`
- Create: `packages/shared/src/constants/index.ts`
- Create: `packages/shared/src/constants/app-names.ts`
- Create: `packages/shared/src/constants/events.ts`

- [ ] **Step 1: Write failing test for format utility**

Create `packages/shared/__tests__/format.test.ts`:

```ts
import { describe, it, expect } from 'vitest';
import { formatDate, formatCurrency } from '../src/utils/format';

describe('formatDate', () => {
  it('should format Date object to YYYY-MM-DD string', () => {
    const date = new Date('2026-01-15');
    expect(formatDate(date)).toBe('2026-01-15');
  });

  it('should format ISO string input', () => {
    expect(formatDate('2026-06-22')).toBe('2026-06-22');
  });
});

describe('formatCurrency', () => {
  it('should format number to CNY currency string', () => {
    expect(formatCurrency(1234.56)).toBe('¥1,234.56');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd packages/shared && npx vitest run
```

Expected: FAIL — "Cannot find module '../src/utils/format'"

- [ ] **Step 3: Create packages/shared/package.json**

```json
{
  "name": "@ai-design/shared",
  "version": "0.0.0",
  "private": true,
  "main": "./src/index.ts",
  "types": "./src/index.ts",
  "scripts": {
    "test": "vitest run",
    "test:watch": "vitest",
    "lint": "eslint src/ --ext .ts"
  },
  "devDependencies": {
    "vitest": "^1.2.0"
  }
}
```

- [ ] **Step 4: Create packages/shared/tsconfig.json**

```json
{
  "extends": "../../tsconfig.base.json",
  "compilerOptions": {
    "outDir": "./dist",
    "rootDir": "./src"
  },
  "include": ["src"]
}
```

- [ ] **Step 5: Create packages/shared/src/utils/format.ts**

```ts
/**
 * Format a Date or date string to YYYY-MM-DD format.
 */
export function formatDate(input: Date | string): string {
  const date = typeof input === 'string' ? new Date(input) : input;
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

/**
 * Format a number to CNY currency string.
 */
export function formatCurrency(amount: number): string {
  return `¥${amount.toLocaleString('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}
```

- [ ] **Step 6: Create packages/shared/src/utils/storage.ts**

```ts
const PREFIX = 'ai_design_';

export const storage = {
  get<T = string>(key: string): T | null {
    try {
      const raw = localStorage.getItem(PREFIX + key);
      if (raw === null) return null;
      return JSON.parse(raw) as T;
    } catch {
      return null;
    }
  },

  set<T = string>(key: string, value: T): void {
    localStorage.setItem(PREFIX + key, JSON.stringify(value));
  },

  remove(key: string): void {
    localStorage.removeItem(PREFIX + key);
  },

  clear(): void {
    const keysToRemove: string[] = [];
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k && k.startsWith(PREFIX)) {
        keysToRemove.push(k);
      }
    }
    keysToRemove.forEach((k) => localStorage.removeItem(k));
  },
};
```

- [ ] **Step 7: Create packages/shared/src/utils/index.ts**

```ts
export { formatDate, formatCurrency } from './format';
export { storage } from './storage';
```

- [ ] **Step 8: Create types files**

`packages/shared/src/types/global-state.ts`:

```ts
/** Global state shape shared across micro-apps via qiankun initGlobalState */
export interface GlobalState {
  /** Current authenticated user info */
  user?: {
    id: string;
    name: string;
    avatar?: string;
  };
  /** Current tenant / workspace info */
  tenant?: {
    id: string;
    name: string;
  };
  /** Cross-app notification event */
  event?: {
    type: string;
    payload?: unknown;
    timestamp: number;
  };
}
```

`packages/shared/src/types/api.ts`:

```ts
/** Standard API response envelope */
export interface ApiResponse<T = unknown> {
  code: number;
  data: T;
  message: string;
}

/** Paginated list response */
export interface PaginatedResponse<T> {
  list: T[];
  total: number;
  page: number;
  pageSize: number;
}

/** API error shape */
export interface ApiError {
  code: number;
  message: string;
  details?: unknown;
}
```

`packages/shared/src/types/index.ts`:

```ts
export type { GlobalState } from './global-state';
export type { ApiResponse, PaginatedResponse, ApiError } from './api';
```

- [ ] **Step 9: Create API request module**

`packages/shared/src/api/request.ts`:

```ts
import axios, { type AxiosInstance, type AxiosRequestConfig } from 'axios';
import type { ApiResponse } from '../types/api';

const instance: AxiosInstance = axios.create({
  baseURL: '/api',
  timeout: 15000,
  headers: { 'Content-Type': 'application/json' },
});

// Request interceptor
instance.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('ai_design_token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error),
);

// Response interceptor
instance.interceptors.response.use(
  (response) => response.data,
  (error) => {
    if (error.response?.status === 401) {
      // Clear token and redirect to login (handled by base app)
      localStorage.removeItem('ai_design_token');
      window.dispatchEvent(new CustomEvent('auth:unauthorized'));
    }
    return Promise.reject(error);
  },
);

export async function request<T>(config: AxiosRequestConfig): Promise<ApiResponse<T>> {
  return instance.request(config);
}

export async function get<T>(
  url: string,
  params?: Record<string, unknown>,
): Promise<ApiResponse<T>> {
  return instance.get(url, { params });
}

export async function post<T>(url: string, data?: unknown): Promise<ApiResponse<T>> {
  return instance.post(url, data);
}

export const http = instance;
```

`packages/shared/src/api/index.ts`:

```ts
export { request, get, post, http } from './request';
```

- [ ] **Step 10: Create constants**

`packages/shared/src/constants/app-names.ts`:

```ts
/** Sub-app name constants — keep in sync with registerMicroApps config */
export const APP_NAMES = {
  MAIN: 'main',
  AI_CHAT: 'ai-chat-app',
  AI_GENERATION: 'ai-generation-app',
  AI_WORKFLOW: 'ai-workflow',
} as const;

/** Route path prefixes for each sub-app */
export const APP_ROUTES = {
  [APP_NAMES.AI_CHAT]: '/ai-chat',
  [APP_NAMES.AI_GENERATION]: '/ai-generation',
  [APP_NAMES.AI_WORKFLOW]: '/ai-workflow',
} as const;
```

`packages/shared/src/constants/events.ts`:

```ts
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
```

`packages/shared/src/constants/index.ts`:

```ts
export { APP_NAMES, APP_ROUTES } from './app-names';
export { GLOBAL_EVENTS } from './events';
```

- [ ] **Step 11: Create main index**

`packages/shared/src/index.ts`:

```ts
export * from './types';
export * from './utils';
export * from './api';
export * from './constants';
```

- [ ] **Step 12: Install shared dependencies**

```bash
cd packages/shared && pnpm add axios
```

- [ ] **Step 13: Run tests to verify they pass**

```bash
cd packages/shared && pnpm test
```

Expected: All 3 tests PASS.

- [ ] **Step 14: Commit**

```bash
git add packages/shared/ pnpm-lock.yaml
git commit -m "feat: add packages/shared — types, utils, API, constants"
```

### Task 3.2: packages/micro-core

**Files:**

- Create: `packages/micro-core/package.json`
- Create: `packages/micro-core/tsconfig.json`
- Create: `packages/micro-core/src/index.ts`
- Create: `packages/micro-core/src/apps-config.ts`
- Create: `packages/micro-core/src/register.ts`
- Create: `packages/micro-core/src/lifecycle.ts`
- Create: `packages/micro-core/src/communication.ts`
- Create: `packages/micro-core/src/prefetch.ts`

- [ ] **Step 1: Write failing test for apps-config**

Create `packages/micro-core/__tests__/apps-config.test.ts`:

```ts
import { describe, it, expect } from 'vitest';
import { getAppConfigs, type AppConfig } from '../src/apps-config';

describe('getAppConfigs', () => {
  it('should return configs for all three sub-apps', () => {
    const configs = getAppConfigs();
    expect(configs).toHaveLength(3);

    const names = configs.map((c) => c.name);
    expect(names).toContain('ai-chat-app');
    expect(names).toContain('ai-generation-app');
    expect(names).toContain('ai-workflow');
  });

  it('should have required fields on each config', () => {
    const configs = getAppConfigs();
    for (const cfg of configs) {
      expect(cfg).toHaveProperty('name');
      expect(cfg).toHaveProperty('entry');
      expect(cfg).toHaveProperty('container');
      expect(cfg).toHaveProperty('activeRule');
    }
  });

  it('should use unique containers per app', () => {
    const configs = getAppConfigs();
    const containers = configs.map((c) => c.container);
    expect(new Set(containers).size).toBe(3);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd packages/micro-core && npx vitest run
```

Expected: FAIL — module not found.

- [ ] **Step 3: Create packages/micro-core/package.json**

```json
{
  "name": "@ai-design/micro-core",
  "version": "0.0.0",
  "private": true,
  "main": "./src/index.ts",
  "types": "./src/index.ts",
  "scripts": {
    "test": "vitest run",
    "test:watch": "vitest",
    "lint": "eslint src/ --ext .ts"
  },
  "dependencies": {
    "@ai-design/shared": "workspace:*",
    "qiankun": "^2.10.16"
  },
  "devDependencies": {
    "vitest": "^1.2.0"
  }
}
```

- [ ] **Step 4: Create packages/micro-core/tsconfig.json**

```json
{
  "extends": "../../tsconfig.base.json",
  "compilerOptions": {
    "outDir": "./dist",
    "rootDir": "./src"
  },
  "include": ["src"]
}
```

- [ ] **Step 5: Create packages/micro-core/src/apps-config.ts**

```ts
import { APP_NAMES, APP_ROUTES } from '@ai-design/shared';

export interface AppConfig {
  name: string;
  entry: string;
  container: string;
  activeRule: string;
  props?: Record<string, unknown>;
}

const ENTRY_MAP: Record<string, { dev: string; prod: string }> = {
  [APP_NAMES.AI_CHAT]: {
    dev: '//localhost:8001',
    prod: '//cdn.example.com/ai-chat-app',
  },
  [APP_NAMES.AI_GENERATION]: {
    dev: '//localhost:8002',
    prod: '//cdn.example.com/ai-generation-app',
  },
  [APP_NAMES.AI_WORKFLOW]: {
    dev: '//localhost:8003',
    prod: '//cdn.example.com/ai-workflow',
  },
};

const isDev = process.env.NODE_ENV === 'development';

/** Build the sub-app registration config list */
export function getAppConfigs(): AppConfig[] {
  return [
    {
      name: APP_NAMES.AI_CHAT,
      entry: isDev ? ENTRY_MAP[APP_NAMES.AI_CHAT].dev : ENTRY_MAP[APP_NAMES.AI_CHAT].prod,
      container: '#sub-app-chat',
      activeRule: APP_ROUTES[APP_NAMES.AI_CHAT],
    },
    {
      name: APP_NAMES.AI_GENERATION,
      entry: isDev
        ? ENTRY_MAP[APP_NAMES.AI_GENERATION].dev
        : ENTRY_MAP[APP_NAMES.AI_GENERATION].prod,
      container: '#sub-app-generation',
      activeRule: APP_ROUTES[APP_NAMES.AI_GENERATION],
    },
    {
      name: APP_NAMES.AI_WORKFLOW,
      entry: isDev ? ENTRY_MAP[APP_NAMES.AI_WORKFLOW].dev : ENTRY_MAP[APP_NAMES.AI_WORKFLOW].prod,
      container: '#sub-app-workflow',
      activeRule: APP_ROUTES[APP_NAMES.AI_WORKFLOW],
    },
  ];
}
```

- [ ] **Step 6: Create packages/micro-core/src/register.ts**

```ts
import { registerMicroApps, start, type RegistrableApp, type StartOpts } from 'qiankun';
import type { AppConfig } from './apps-config';
import { getGlobalLifecycleHooks } from './lifecycle';
import { initCommunication } from './communication';
import { doPrefetch } from './prefetch';

let started = false;

/**
 * Register all sub-apps and start qiankun.
 * Should be called once from the base app after Vue/React app is mounted.
 */
export function setupMicroApps(apps: AppConfig[], startOpts?: StartOpts): void {
  if (started) return;

  // Init global state communication
  initCommunication();

  // Transform our config to qiankun's format
  const microApps: RegistrableApp<Record<string, unknown>>[] = apps.map((app) => ({
    name: app.name,
    entry: app.entry,
    container: app.container,
    activeRule: app.activeRule,
    props: app.props || {},
  }));

  // Register
  registerMicroApps(microApps, getGlobalLifecycleHooks());

  // Start
  start({
    prefetch: false, // We handle prefetch separately
    sandbox: {
      experimentalStyleIsolation: true,
    },
    ...startOpts,
  });

  // Trigger prefetch after start
  doPrefetch(apps.map((a) => a.name));

  started = true;
}
```

- [ ] **Step 7: Create packages/micro-core/src/lifecycle.ts**

```ts
import type { LifeCycles } from 'qiankun';

/**
 * Global lifecycle hooks — called for every sub-app load/unmount cycle.
 * Use for global loading indicators, error reporting, etc.
 */
export function getGlobalLifecycleHooks(): LifeCycles {
  return {
    beforeLoad: async (app) => {
      console.log(`[micro-core] Loading ${app.name}...`);
    },

    beforeMount: async (app) => {
      console.log(`[micro-core] Mounting ${app.name}...`);
    },

    afterMount: async (app) => {
      console.log(`[micro-core] ${app.name} mounted`);
    },

    beforeUnmount: async (app) => {
      console.log(`[micro-core] Unmounting ${app.name}...`);
    },

    afterUnmount: async (app) => {
      console.log(`[micro-core] ${app.name} unmounted`);
    },
  };
}
```

- [ ] **Step 8: Create packages/micro-core/src/communication.ts**

```ts
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
  actions.onGlobalStateChange(callback, fireImmediately);
}

/**
 * Update global state — notifies all sub-apps.
 */
export function setGlobalState(state: Partial<GlobalState>): void {
  actions.setGlobalState(state);
}

/**
 * Remove all global state listeners.
 */
export function offGlobalStateChange(): void {
  actions.offGlobalStateChange();
}
```

- [ ] **Step 9: Create packages/micro-core/src/prefetch.ts**

```ts
import { prefetchApps } from 'qiankun';

/**
 * Prefetch sub-app assets after base app is idle.
 * Call after qiankun start().
 */
export function doPrefetch(appNames: string[]): void {
  if (typeof requestIdleCallback === 'function') {
    requestIdleCallback(() => {
      prefetchApps(appNames);
    });
  } else {
    setTimeout(() => {
      prefetchApps(appNames);
    }, 3000);
  }
}
```

- [ ] **Step 10: Create packages/micro-core/src/index.ts**

```ts
export { getAppConfigs } from './apps-config';
export type { AppConfig } from './apps-config';
export { setupMicroApps } from './register';
export { getGlobalLifecycleHooks } from './lifecycle';
export {
  initCommunication,
  onGlobalStateChange,
  setGlobalState,
  offGlobalStateChange,
} from './communication';
export { doPrefetch } from './prefetch';
```

- [ ] **Step 11: Run tests to verify they pass**

```bash
cd packages/micro-core && pnpm test
```

Expected: All 3 tests PASS.

- [ ] **Step 12: Commit**

```bash
git add packages/micro-core/ pnpm-lock.yaml
git commit -m "feat: add packages/micro-core — qiankun encapsulation layer"
```

---

## Phase 4: Base App (main)

### Task 4.1: Scaffold main app

**Files:**

- Create: `apps/main/package.json`
- Create: `apps/main/tsconfig.json`
- Create: `apps/main/webpack/webpack.common.js`
- Create: `apps/main/webpack/webpack.dev.js`
- Create: `apps/main/webpack/webpack.prod.js`
- Create: `apps/main/postcss.config.js`
- Create: `apps/main/tailwind.config.js`
- Create: `apps/main/public/index.html`
- Create: `apps/main/src/main.ts`
- Create: `apps/main/src/App.vue`
- Create: `apps/main/src/shims-vue.d.ts`

- [ ] **Step 1: Create apps/main/package.json**

```json
{
  "name": "@ai-design/main",
  "version": "0.0.0",
  "private": true,
  "scripts": {
    "dev": "webpack serve --config webpack/webpack.dev.js",
    "build": "webpack --config webpack/webpack.prod.js",
    "lint": "eslint src/ --ext .ts,.vue"
  },
  "dependencies": {
    "@ai-design/micro-core": "workspace:*",
    "@ai-design/shared": "workspace:*",
    "pinia": "^2.1.7",
    "qiankun": "^2.10.16",
    "vue": "^3.4.15",
    "vue-router": "^4.2.5"
  },
  "devDependencies": {
    "@types/node": "^20.11.5",
    "autoprefixer": "^10.4.17",
    "css-loader": "^6.9.1",
    "html-webpack-plugin": "^5.6.0",
    "mini-css-extract-plugin": "^2.7.7",
    "postcss": "^8.4.33",
    "postcss-loader": "^8.1.0",
    "style-loader": "^3.3.4",
    "tailwindcss": "^3.4.1",
    "ts-loader": "^9.5.1",
    "typescript": "^5.3.3",
    "vue-loader": "^17.4.2",
    "@vue/compiler-sfc": "^3.4.15",
    "vue-style-loader": "^4.1.3",
    "webpack": "^5.90.0",
    "webpack-cli": "^5.1.4",
    "webpack-dev-server": "^4.15.2",
    "webpack-merge": "^5.10.0"
  }
}
```

- [ ] **Step 2: Create apps/main/tsconfig.json**

```json
{
  "extends": "../../tsconfig.base.json",
  "compilerOptions": {
    "outDir": "./dist",
    "rootDir": "./src",
    "jsx": "preserve",
    "jsxImportSource": "vue",
    "types": ["webpack-env"]
  },
  "include": ["src/**/*.ts", "src/**/*.vue", "src/**/*.d.ts"],
  "references": [{ "path": "../../packages/shared" }, { "path": "../../packages/micro-core" }]
}
```

- [ ] **Step 3: Create apps/main/webpack/webpack.common.js**

```js
const path = require('path');
const HtmlWebpackPlugin = require('html-webpack-plugin');
const { VueLoaderPlugin } = require('vue-loader');
const MiniCssExtractPlugin = require('mini-css-extract-plugin');

const isDev = process.env.NODE_ENV === 'development';

module.exports = {
  entry: path.resolve(__dirname, '../src/main.ts'),
  output: {
    path: path.resolve(__dirname, '../dist'),
    filename: 'js/[name].[contenthash:8].js',
    publicPath: '/',
    clean: true,
  },
  resolve: {
    extensions: ['.ts', '.tsx', '.js', '.jsx', '.vue', '.json'],
    alias: {
      '@': path.resolve(__dirname, '../src'),
      '@ai-design/shared': path.resolve(__dirname, '../../../packages/shared/src'),
      '@ai-design/micro-core': path.resolve(__dirname, '../../../packages/micro-core/src'),
    },
  },
  module: {
    rules: [
      {
        test: /\.vue$/,
        use: 'vue-loader',
      },
      {
        test: /\.tsx?$/,
        use: {
          loader: 'ts-loader',
          options: {
            appendTsSuffixTo: [/\.vue$/],
            transpileOnly: true,
          },
        },
        exclude: /node_modules/,
      },
      {
        test: /\.css$/,
        oneOf: [
          {
            resourceQuery: /module/,
            use: [
              isDev ? 'vue-style-loader' : MiniCssExtractPlugin.loader,
              {
                loader: 'css-loader',
                options: {
                  modules: { localIdentName: '[local]_[hash:base64:8]' },
                },
              },
              'postcss-loader',
            ],
          },
          {
            use: [
              isDev ? 'vue-style-loader' : MiniCssExtractPlugin.loader,
              'css-loader',
              'postcss-loader',
            ],
          },
        ],
      },
      {
        test: /\.(png|jpe?g|gif|svg|webp)$/i,
        type: 'asset/resource',
        generator: {
          filename: 'images/[name].[hash:8][ext]',
        },
      },
      {
        test: /\.(woff2?|eot|ttf|otf)$/i,
        type: 'asset/resource',
        generator: {
          filename: 'fonts/[name].[hash:8][ext]',
        },
      },
    ],
  },
  plugins: [
    new VueLoaderPlugin(),
    new HtmlWebpackPlugin({
      template: path.resolve(__dirname, '../public/index.html'),
      title: 'AI Design Platform',
      favicon: false,
    }),
    ...(isDev
      ? []
      : [
          new MiniCssExtractPlugin({
            filename: 'css/[name].[contenthash:8].css',
          }),
        ]),
  ],
};
```

- [ ] **Step 4: Create apps/main/webpack/webpack.dev.js**

```js
const { merge } = require('webpack-merge');
const common = require('./webpack.common');

module.exports = merge(common, {
  mode: 'development',
  devtool: 'eval-cheap-module-source-map',
  devServer: {
    port: 8000,
    hot: true,
    open: false,
    historyApiFallback: true,
    headers: {
      'Access-Control-Allow-Origin': '*',
    },
  },
});
```

- [ ] **Step 5: Create apps/main/webpack/webpack.prod.js**

```js
const { merge } = require('webpack-merge');
const common = require('./webpack.common');

module.exports = merge(common, {
  mode: 'production',
  devtool: 'source-map',
  optimization: {
    splitChunks: {
      chunks: 'all',
      cacheGroups: {
        vendor: {
          test: /[\\/]node_modules[\\/]/,
          name: 'vendor',
          chunks: 'all',
        },
      },
    },
  },
});
```

- [ ] **Step 6: Create apps/main/postcss.config.js**

```js
module.exports = {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
};
```

- [ ] **Step 7: Create apps/main/tailwind.config.js**

```js
/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./src/**/*.{vue,ts,tsx,js,jsx}', './public/index.html'],
  theme: {
    extend: {},
  },
  plugins: [],
};
```

- [ ] **Step 8: Create apps/main/public/index.html**

```html
<!DOCTYPE html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>AI Design Platform</title>
  </head>
  <body>
    <div id="app"></div>
  </body>
</html>
```

- [ ] **Step 9: Create apps/main/src/main.ts**

```ts
import { createApp } from 'vue';
import { createPinia } from 'pinia';
import App from './App.vue';
import { setupMicroApps, getAppConfigs } from '@ai-design/micro-core';
import './styles/global.css';

function bootstrap(): void {
  const app = createApp(App);
  const pinia = createPinia();

  app.use(pinia);
  app.mount('#app');

  // After Vue is mounted, register and start qiankun sub-apps
  setupMicroApps(getAppConfigs());
}

bootstrap();
```

- [ ] **Step 10: Create apps/main/src/App.vue**

```vue
<template>
  <div id="main-app" class="flex h-screen bg-gray-50">
    <aside class="w-60 bg-gray-900 text-white flex flex-col">
      <div class="px-6 py-4 text-lg font-bold border-b border-gray-700">AI Design</div>
      <nav class="flex-1 px-4 py-4 space-y-1">
        <router-link
          to="/"
          class="block px-3 py-2 rounded text-sm hover:bg-gray-700 transition-colors"
        >
          首页
        </router-link>
        <router-link
          to="/ai-chat"
          class="block px-3 py-2 rounded text-sm hover:bg-gray-700 transition-colors"
        >
          AI 对话
        </router-link>
        <router-link
          to="/ai-generation"
          class="block px-3 py-2 rounded text-sm hover:bg-gray-700 transition-colors"
        >
          AI 生成
        </router-link>
        <router-link
          to="/ai-workflow"
          class="block px-3 py-2 rounded text-sm hover:bg-gray-700 transition-colors"
        >
          AI 工作流
        </router-link>
      </nav>
    </aside>

    <main class="flex-1 flex flex-col overflow-hidden">
      <header class="h-14 border-b bg-white flex items-center px-6 shadow-sm">
        <span class="text-sm text-gray-500">AI Design Platform v0.0.0</span>
      </header>

      <div class="flex-1 overflow-auto p-6">
        <router-view />
      </div>
    </main>
  </div>
</template>

<script setup lang="ts">
// Base app shell with sidebar layout
</script>
```

- [ ] **Step 11: Create apps/main/src/shims-vue.d.ts**

```ts
declare module '*.vue' {
  import type { DefineComponent } from 'vue';
  const component: DefineComponent<object, object, unknown>;
  export default component;
}
```

- [ ] **Step 12: Create apps/main/src/styles/global.css**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

body {
  margin: 0;
  padding: 0;
}
```

- [ ] **Step 13: Install main app dependencies**

```bash
cd apps/main && pnpm install
```

- [ ] **Step 14: Verify main app builds**

```bash
cd apps/main && pnpm build
```

Expected: Build completes, `apps/main/dist/` created with `index.html` and JS bundles.

- [ ] **Step 15: Commit**

```bash
git add apps/main/ pnpm-lock.yaml
git commit -m "feat: scaffold main base app with Vue3 + Webpack + Tailwind CSS"
```

---

## Phase 5: Sub-App 1 — ai-chat-app (Vue3)

### Task 5.1: Scaffold ai-chat-app

**Files:**

- Create: `apps/ai-chat-app/package.json`
- Create: `apps/ai-chat-app/tsconfig.json`
- Create: `apps/ai-chat-app/webpack/webpack.common.js`
- Create: `apps/ai-chat-app/webpack/webpack.dev.js`
- Create: `apps/ai-chat-app/webpack/webpack.prod.js`
- Create: `apps/ai-chat-app/postcss.config.js`
- Create: `apps/ai-chat-app/tailwind.config.js`
- Create: `apps/ai-chat-app/public/index.html`
- Create: `apps/ai-chat-app/src/main.ts`
- Create: `apps/ai-chat-app/src/App.vue`
- Create: `apps/ai-chat-app/src/router/index.ts`
- Create: `apps/ai-chat-app/src/views/Home.vue`
- Create: `apps/ai-chat-app/src/views/About.vue`
- Create: `apps/ai-chat-app/src/shims-vue.d.ts`
- Create: `apps/ai-chat-app/src/styles/global.css`

- [ ] **Step 1: Create apps/ai-chat-app/package.json**

```json
{
  "name": "@ai-design/ai-chat-app",
  "version": "0.0.0",
  "private": true,
  "scripts": {
    "dev": "webpack serve --config webpack/webpack.dev.js",
    "build": "webpack --config webpack/webpack.prod.js",
    "lint": "eslint src/ --ext .ts,.vue"
  },
  "dependencies": {
    "@ai-design/shared": "workspace:*",
    "@ai-design/micro-core": "workspace:*",
    "pinia": "^2.1.7",
    "vue": "^3.4.15",
    "vue-router": "^4.2.5"
  },
  "devDependencies": {
    "@types/node": "^20.11.5",
    "autoprefixer": "^10.4.17",
    "css-loader": "^6.9.1",
    "html-webpack-plugin": "^5.6.0",
    "mini-css-extract-plugin": "^2.7.7",
    "postcss": "^8.4.33",
    "postcss-loader": "^8.1.0",
    "style-loader": "^3.3.4",
    "tailwindcss": "^3.4.1",
    "ts-loader": "^9.5.1",
    "typescript": "^5.3.3",
    "vue-loader": "^17.4.2",
    "@vue/compiler-sfc": "^3.4.15",
    "vue-style-loader": "^4.1.3",
    "webpack": "^5.90.0",
    "webpack-cli": "^5.1.4",
    "webpack-dev-server": "^4.15.2",
    "webpack-merge": "^5.10.0"
  }
}
```

- [ ] **Step 2: Create apps/ai-chat-app/tsconfig.json**

```json
{
  "extends": "../../tsconfig.base.json",
  "compilerOptions": {
    "outDir": "./dist",
    "rootDir": "./src",
    "jsx": "preserve",
    "jsxImportSource": "vue"
  },
  "include": ["src/**/*.ts", "src/**/*.vue", "src/**/*.d.ts"],
  "references": [{ "path": "../../packages/shared" }, { "path": "../../packages/micro-core" }]
}
```

- [ ] **Step 3: Create apps/ai-chat-app/webpack/webpack.common.js**

```js
const path = require('path');
const HtmlWebpackPlugin = require('html-webpack-plugin');
const { VueLoaderPlugin } = require('vue-loader');
const MiniCssExtractPlugin = require('mini-css-extract-plugin');

const isDev = process.env.NODE_ENV === 'development';
const appName = 'ai-chat-app';

module.exports = {
  entry: path.resolve(__dirname, '../src/main.ts'),
  output: {
    path: path.resolve(__dirname, '../dist'),
    filename: 'js/[name].[contenthash:8].js',
    library: `${appName}-[name]`,
    libraryTarget: 'umd',
    globalObject: 'window',
    publicPath: isDev ? '//localhost:8001/' : `/`,
  },
  resolve: {
    extensions: ['.ts', '.tsx', '.js', '.jsx', '.vue', '.json'],
    alias: {
      '@': path.resolve(__dirname, '../src'),
      '@ai-design/shared': path.resolve(__dirname, '../../../packages/shared/src'),
      '@ai-design/micro-core': path.resolve(__dirname, '../../../packages/micro-core/src'),
    },
  },
  module: {
    rules: [
      {
        test: /\.vue$/,
        use: 'vue-loader',
      },
      {
        test: /\.tsx?$/,
        use: {
          loader: 'ts-loader',
          options: {
            appendTsSuffixTo: [/\.vue$/],
            transpileOnly: true,
          },
        },
        exclude: /node_modules/,
      },
      {
        test: /\.css$/,
        use: [
          isDev ? 'vue-style-loader' : MiniCssExtractPlugin.loader,
          'css-loader',
          'postcss-loader',
        ],
      },
      {
        test: /\.(png|jpe?g|gif|svg|webp)$/i,
        type: 'asset/resource',
      },
      {
        test: /\.(woff2?|eot|ttf|otf)$/i,
        type: 'asset/resource',
      },
    ],
  },
  plugins: [
    new VueLoaderPlugin(),
    new HtmlWebpackPlugin({
      template: path.resolve(__dirname, '../public/index.html'),
      title: 'AI Chat',
    }),
    ...(isDev
      ? []
      : [
          new MiniCssExtractPlugin({
            filename: 'css/[name].[contenthash:8].css',
          }),
        ]),
  ],
};
```

- [ ] **Step 4: Create apps/ai-chat-app/webpack/webpack.dev.js**

```js
const { merge } = require('webpack-merge');
const common = require('./webpack.common');

module.exports = merge(common, {
  mode: 'development',
  devtool: 'eval-cheap-module-source-map',
  devServer: {
    port: 8001,
    hot: true,
    open: false,
    historyApiFallback: true,
    headers: {
      'Access-Control-Allow-Origin': '*',
    },
  },
});
```

- [ ] **Step 5: Create apps/ai-chat-app/webpack/webpack.prod.js**

```js
const { merge } = require('webpack-merge');
const common = require('./webpack.common');

module.exports = merge(common, {
  mode: 'production',
  devtool: 'source-map',
});
```

- [ ] **Step 6: Create apps/ai-chat-app/postcss.config.js** (same as main)

```js
module.exports = {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
};
```

- [ ] **Step 7: Create apps/ai-chat-app/tailwind.config.js**

```js
/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./src/**/*.{vue,ts,tsx,js,jsx}', './public/index.html'],
  theme: {
    extend: {},
  },
  plugins: [],
};
```

- [ ] **Step 8: Create apps/ai-chat-app/public/index.html**

```html
<!DOCTYPE html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>AI Chat</title>
  </head>
  <body>
    <div id="app"></div>
  </body>
</html>
```

- [ ] **Step 9: Create apps/ai-chat-app/src/main.ts** (qiankun lifecycle)

```ts
import { createApp, type App as VueApp } from 'vue';
import { createPinia } from 'pinia';
import { createRouter, createWebHistory, type Router } from 'vue-router';
import App from './App.vue';
import { routes } from './router';
import './styles/global.css';

let app: VueApp | null = null;
let router: Router | null = null;

function render(props: Record<string, unknown> = {}): void {
  const container = (props.container as HTMLElement) || document.getElementById('app');
  if (!container) return;

  app = createApp(App);
  const pinia = createPinia();

  router = createRouter({
    history: createWebHistory(
      (window as unknown as Record<string, unknown>).__POWERED_BY_QIANKUN__ ? '/ai-chat' : '/',
    ),
    routes,
  });

  app.use(pinia);
  app.use(router);
  app.mount(container.querySelector('#app') || container);
}

function unmount(): void {
  app?.unmount();
  app = null;
  router = null;
}

// Standalone mode — running outside qiankun (dev server)
if (!(window as unknown as Record<string, unknown>).__POWERED_BY_QIANKUN__) {
  render();
}

// ---- Qiankun lifecycle exports ----
export async function bootstrap(): Promise<void> {
  console.log('[ai-chat-app] bootstrap');
}

export async function mount(props: Record<string, unknown>): Promise<void> {
  console.log('[ai-chat-app] mount', props);
  render(props);
}

export async function unmount(_props: Record<string, unknown>): Promise<void> {
  console.log('[ai-chat-app] unmount');
  unmount();
}
```

- [ ] **Step 10: Create apps/ai-chat-app/src/App.vue**

```vue
<template>
  <div class="ai-chat-app p-6">
    <h1 class="text-2xl font-bold text-gray-800 mb-4">AI 对话</h1>
    <nav class="flex space-x-4 mb-6">
      <router-link to="/" class="text-blue-600 hover:underline">首页</router-link>
      <router-link to="/about" class="text-blue-600 hover:underline">关于</router-link>
    </nav>
    <router-view />
  </div>
</template>

<script setup lang="ts">
import { onGlobalStateChange } from '@ai-design/micro-core';

// Listen for global state changes from base app
onGlobalStateChange((state, prev) => {
  console.log('[ai-chat-app] global state changed:', state, prev);
});
</script>
```

- [ ] **Step 11: Create apps/ai-chat-app/src/router/index.ts**

```ts
import type { RouteRecordRaw } from 'vue-router';
import Home from '../views/Home.vue';
import About from '../views/About.vue';

export const routes: RouteRecordRaw[] = [
  { path: '/', name: 'Home', component: Home },
  { path: '/about', name: 'About', component: About },
];
```

- [ ] **Step 12: Create apps/ai-chat-app/src/views/Home.vue**

```vue
<template>
  <div class="bg-white rounded-lg shadow p-6">
    <p class="text-gray-600">欢迎使用 AI 对话功能</p>
  </div>
</template>

<script setup lang="ts"></script>
```

- [ ] **Step 13: Create apps/ai-chat-app/src/views/About.vue**

```vue
<template>
  <div class="bg-white rounded-lg shadow p-6">
    <p class="text-gray-600">AI 对话子应用 v0.0.0</p>
  </div>
</template>
```

- [ ] **Step 14: Create apps/ai-chat-app/src/shims-vue.d.ts** (same as main)

```ts
declare module '*.vue' {
  import type { DefineComponent } from 'vue';
  const component: DefineComponent<object, object, unknown>;
  export default component;
}
```

- [ ] **Step 15: Create apps/ai-chat-app/src/styles/global.css** (same as main)

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

body {
  margin: 0;
  padding: 0;
}
```

- [ ] **Step 16: Install and build**

```bash
cd apps/ai-chat-app && pnpm install && pnpm build
```

Expected: Build succeeds. `apps/ai-chat-app/dist/` created.

- [ ] **Step 17: Commit**

```bash
git add apps/ai-chat-app/ pnpm-lock.yaml
git commit -m "feat: scaffold ai-chat-app with Vue3 + Webpack + qiankun lifecycle"
```

---

## Phase 6: Sub-App 2 — ai-generation-app (Vue3)

This is structurally identical to ai-chat-app. Differences: app name, port 8002, route prefix `/ai-generation`, and view text.

### Task 6.1: Scaffold ai-generation-app

**Files:**

- Create: `apps/ai-generation-app/package.json`
- Create: `apps/ai-generation-app/tsconfig.json`
- Create: `apps/ai-generation-app/webpack/webpack.common.js`
- Create: `apps/ai-generation-app/webpack/webpack.dev.js`
- Create: `apps/ai-generation-app/webpack/webpack.prod.js`
- Create: `apps/ai-generation-app/postcss.config.js`
- Create: `apps/ai-generation-app/tailwind.config.js`
- Create: `apps/ai-generation-app/public/index.html`
- Create: `apps/ai-generation-app/src/main.ts`
- Create: `apps/ai-generation-app/src/App.vue`
- Create: `apps/ai-generation-app/src/router/index.ts`
- Create: `apps/ai-generation-app/src/views/Home.vue`
- Create: `apps/ai-generation-app/src/views/About.vue`
- Create: `apps/ai-generation-app/src/shims-vue.d.ts`
- Create: `apps/ai-generation-app/src/styles/global.css`

- [ ] **Step 1: Create apps/ai-generation-app/package.json**

```json
{
  "name": "@ai-design/ai-generation-app",
  "version": "0.0.0",
  "private": true,
  "scripts": {
    "dev": "webpack serve --config webpack/webpack.dev.js",
    "build": "webpack --config webpack/webpack.prod.js",
    "lint": "eslint src/ --ext .ts,.vue"
  },
  "dependencies": {
    "@ai-design/shared": "workspace:*",
    "@ai-design/micro-core": "workspace:*",
    "pinia": "^2.1.7",
    "vue": "^3.4.15",
    "vue-router": "^4.2.5"
  },
  "devDependencies": {
    "@types/node": "^20.11.5",
    "autoprefixer": "^10.4.17",
    "css-loader": "^6.9.1",
    "html-webpack-plugin": "^5.6.0",
    "mini-css-extract-plugin": "^2.7.7",
    "postcss": "^8.4.33",
    "postcss-loader": "^8.1.0",
    "style-loader": "^3.3.4",
    "tailwindcss": "^3.4.1",
    "ts-loader": "^9.5.1",
    "typescript": "^5.3.3",
    "vue-loader": "^17.4.2",
    "@vue/compiler-sfc": "^3.4.15",
    "vue-style-loader": "^4.1.3",
    "webpack": "^5.90.0",
    "webpack-cli": "^5.1.4",
    "webpack-dev-server": "^4.15.2",
    "webpack-merge": "^5.10.0"
  }
}
```

- [ ] **Step 2: Write failing test for ai-generation-app routing**

Create `apps/ai-generation-app/__tests__/router.test.ts`:

```ts
import { describe, it, expect } from 'vitest';
import { routes } from '../src/router';

describe('ai-generation-app routes', () => {
  it('should have Home and About routes', () => {
    const names = routes.map((r) => r.name);
    expect(names).toContain('Home');
    expect(names).toContain('About');
  });

  it('should have Home as root path', () => {
    const home = routes.find((r) => r.name === 'Home');
    expect(home?.path).toBe('/');
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

```bash
cd apps/ai-generation-app && npx vitest run
```

Expected: FAIL — module not found.

- [ ] **Step 4: Create apps/ai-generation-app/tsconfig.json**

```json
{
  "extends": "../../tsconfig.base.json",
  "compilerOptions": {
    "outDir": "./dist",
    "rootDir": "./src",
    "jsx": "preserve",
    "jsxImportSource": "vue"
  },
  "include": ["src/**/*.ts", "src/**/*.vue", "src/**/*.d.ts"],
  "references": [{ "path": "../../packages/shared" }, { "path": "../../packages/micro-core" }]
}
```

- [ ] **Step 5: Create apps/ai-generation-app/webpack/webpack.common.js**

```js
const path = require('path');
const HtmlWebpackPlugin = require('html-webpack-plugin');
const { VueLoaderPlugin } = require('vue-loader');
const MiniCssExtractPlugin = require('mini-css-extract-plugin');

const isDev = process.env.NODE_ENV === 'development';
const appName = 'ai-generation-app';

module.exports = {
  entry: path.resolve(__dirname, '../src/main.ts'),
  output: {
    path: path.resolve(__dirname, '../dist'),
    filename: 'js/[name].[contenthash:8].js',
    library: `${appName}-[name]`,
    libraryTarget: 'umd',
    globalObject: 'window',
    publicPath: isDev ? '//localhost:8002/' : `/`,
  },
  resolve: {
    extensions: ['.ts', '.tsx', '.js', '.jsx', '.vue', '.json'],
    alias: {
      '@': path.resolve(__dirname, '../src'),
      '@ai-design/shared': path.resolve(__dirname, '../../../packages/shared/src'),
      '@ai-design/micro-core': path.resolve(__dirname, '../../../packages/micro-core/src'),
    },
  },
  module: {
    rules: [
      { test: /\.vue$/, use: 'vue-loader' },
      {
        test: /\.tsx?$/,
        use: {
          loader: 'ts-loader',
          options: { appendTsSuffixTo: [/\.vue$/], transpileOnly: true },
        },
        exclude: /node_modules/,
      },
      {
        test: /\.css$/,
        use: [
          isDev ? 'vue-style-loader' : MiniCssExtractPlugin.loader,
          'css-loader',
          'postcss-loader',
        ],
      },
      { test: /\.(png|jpe?g|gif|svg|webp)$/i, type: 'asset/resource' },
      { test: /\.(woff2?|eot|ttf|otf)$/i, type: 'asset/resource' },
    ],
  },
  plugins: [
    new VueLoaderPlugin(),
    new HtmlWebpackPlugin({
      template: path.resolve(__dirname, '../public/index.html'),
      title: 'AI Generation',
    }),
    ...(isDev ? [] : [new MiniCssExtractPlugin({ filename: 'css/[name].[contenthash:8].css' })]),
  ],
};
```

- [ ] **Step 6: Create apps/ai-generation-app/webpack/webpack.dev.js**

```js
const { merge } = require('webpack-merge');
const common = require('./webpack.common');

module.exports = merge(common, {
  mode: 'development',
  devtool: 'eval-cheap-module-source-map',
  devServer: {
    port: 8002,
    hot: true,
    open: false,
    historyApiFallback: true,
    headers: {
      'Access-Control-Allow-Origin': '*',
    },
  },
});
```

- [ ] **Step 7: Create apps/ai-generation-app/webpack/webpack.prod.js**

```js
const { merge } = require('webpack-merge');
const common = require('./webpack.common');

module.exports = merge(common, {
  mode: 'production',
  devtool: 'source-map',
});
```

- [ ] **Step 8: Create apps/ai-generation-app/postcss.config.js**

```js
module.exports = {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
};
```

- [ ] **Step 9: Create apps/ai-generation-app/tailwind.config.js**

```js
/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./src/**/*.{vue,ts,tsx,js,jsx}', './public/index.html'],
  theme: { extend: {} },
  plugins: [],
};
```

- [ ] **Step 10: Create apps/ai-generation-app/public/index.html**

```html
<!DOCTYPE html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>AI Generation</title>
  </head>
  <body>
    <div id="app"></div>
  </body>
</html>
```

- [ ] **Step 11: Create apps/ai-generation-app/src/main.ts**

```ts
import { createApp, type App as VueApp } from 'vue';
import { createPinia } from 'pinia';
import { createRouter, createWebHistory, type Router } from 'vue-router';
import App from './App.vue';
import { routes } from './router';
import './styles/global.css';

let app: VueApp | null = null;
let router: Router | null = null;

function render(props: Record<string, unknown> = {}): void {
  const container = (props.container as HTMLElement) || document.getElementById('app');
  if (!container) return;

  app = createApp(App);
  const pinia = createPinia();

  router = createRouter({
    history: createWebHistory(
      (window as unknown as Record<string, unknown>).__POWERED_BY_QIANKUN__
        ? '/ai-generation'
        : '/',
    ),
    routes,
  });

  app.use(pinia);
  app.use(router);
  app.mount(container.querySelector('#app') || container);
}

function unmount(): void {
  app?.unmount();
  app = null;
  router = null;
}

if (!(window as unknown as Record<string, unknown>).__POWERED_BY_QIANKUN__) {
  render();
}

export async function bootstrap(): Promise<void> {
  console.log('[ai-generation-app] bootstrap');
}

export async function mount(props: Record<string, unknown>): Promise<void> {
  console.log('[ai-generation-app] mount', props);
  render(props);
}

export async function unmount(_props: Record<string, unknown>): Promise<void> {
  console.log('[ai-generation-app] unmount');
  unmount();
}
```

- [ ] **Step 12: Create apps/ai-generation-app/src/App.vue**

```vue
<template>
  <div class="ai-generation-app p-6">
    <h1 class="text-2xl font-bold text-gray-800 mb-4">AI 生成</h1>
    <nav class="flex space-x-4 mb-6">
      <router-link to="/" class="text-blue-600 hover:underline">首页</router-link>
      <router-link to="/about" class="text-blue-600 hover:underline">关于</router-link>
    </nav>
    <router-view />
  </div>
</template>

<script setup lang="ts">
import { onGlobalStateChange } from '@ai-design/micro-core';

onGlobalStateChange((state, prev) => {
  console.log('[ai-generation-app] global state changed:', state, prev);
});
</script>
```

- [ ] **Step 13: Create apps/ai-generation-app/src/router/index.ts**

```ts
import type { RouteRecordRaw } from 'vue-router';
import Home from '../views/Home.vue';
import About from '../views/About.vue';

export const routes: RouteRecordRaw[] = [
  { path: '/', name: 'Home', component: Home },
  { path: '/about', name: 'About', component: About },
];
```

- [ ] **Step 14: Create apps/ai-generation-app/src/views/Home.vue**

```vue
<template>
  <div class="bg-white rounded-lg shadow p-6">
    <p class="text-gray-600">欢迎使用 AI 生成功能</p>
  </div>
</template>
```

- [ ] **Step 15: Create apps/ai-generation-app/src/views/About.vue**

```vue
<template>
  <div class="bg-white rounded-lg shadow p-6">
    <p class="text-gray-600">AI 生成子应用 v0.0.0</p>
  </div>
</template>
```

- [ ] **Step 16: Create apps/ai-generation-app/src/shims-vue.d.ts**

```ts
declare module '*.vue' {
  import type { DefineComponent } from 'vue';
  const component: DefineComponent<object, object, unknown>;
  export default component;
}
```

- [ ] **Step 17: Create apps/ai-generation-app/src/styles/global.css**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

body {
  margin: 0;
  padding: 0;
}
```

- [ ] **Step 18: Install, test, and build**

```bash
cd apps/ai-generation-app && pnpm install
```

- [ ] **Step 19: Run tests**

```bash
cd apps/ai-generation-app && npx vitest run
```

Expected: 2 tests PASS.

- [ ] **Step 20: Build**

```bash
cd apps/ai-generation-app && pnpm build
```

Expected: Build succeeds.

- [ ] **Step 21: Commit**

```bash
git add apps/ai-generation-app/ pnpm-lock.yaml
git commit -m "feat: scaffold ai-generation-app with Vue3 + Webpack + qiankun lifecycle"
```

---

## Phase 7: Sub-App 3 — ai-workflow (React)

### Task 7.1: Scaffold ai-workflow

**Files:**

- Create: `apps/ai-workflow/package.json`
- Create: `apps/ai-workflow/tsconfig.json`
- Create: `apps/ai-workflow/webpack/webpack.common.js`
- Create: `apps/ai-workflow/webpack/webpack.dev.js`
- Create: `apps/ai-workflow/webpack/webpack.prod.js`
- Create: `apps/ai-workflow/postcss.config.js`
- Create: `apps/ai-workflow/tailwind.config.js`
- Create: `apps/ai-workflow/public/index.html`
- Create: `apps/ai-workflow/src/main.tsx`
- Create: `apps/ai-workflow/src/App.tsx`
- Create: `apps/ai-workflow/src/router/index.tsx`
- Create: `apps/ai-workflow/src/store/index.ts`
- Create: `apps/ai-workflow/src/store/slices/workflowSlice.ts`
- Create: `apps/ai-workflow/src/pages/Home.tsx`
- Create: `apps/ai-workflow/src/pages/About.tsx`
- Create: `apps/ai-workflow/src/styles/global.css`

- [ ] **Step 1: Write failing test for Redux store**

Create `apps/ai-workflow/__tests__/workflowSlice.test.ts`:

```ts
import { describe, it, expect } from 'vitest';
import workflowReducer, { setLoading, initialState } from '../src/store/slices/workflowSlice';

describe('workflowSlice', () => {
  it('should return the initial state', () => {
    const state = workflowReducer(undefined, { type: '@@INIT' });
    expect(state.loading).toBe(false);
    expect(state.workflows).toEqual([]);
  });

  it('should handle setLoading', () => {
    const state = workflowReducer(initialState, setLoading(true));
    expect(state.loading).toBe(true);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd apps/ai-workflow && npx vitest run
```

Expected: FAIL — module not found.

- [ ] **Step 3: Create apps/ai-workflow/package.json**

```json
{
  "name": "@ai-design/ai-workflow",
  "version": "0.0.0",
  "private": true,
  "scripts": {
    "dev": "webpack serve --config webpack/webpack.dev.js",
    "build": "webpack --config webpack/webpack.prod.js",
    "test": "vitest run",
    "lint": "eslint src/ --ext .ts,.tsx"
  },
  "dependencies": {
    "@ai-design/shared": "workspace:*",
    "@ai-design/micro-core": "workspace:*",
    "@reduxjs/toolkit": "^2.0.1",
    "react": "^18.2.0",
    "react-dom": "^18.2.0",
    "react-redux": "^9.1.0",
    "react-router-dom": "^6.21.3"
  },
  "devDependencies": {
    "@types/node": "^20.11.5",
    "@types/react": "^18.2.48",
    "@types/react-dom": "^18.2.18",
    "autoprefixer": "^10.4.17",
    "css-loader": "^6.9.1",
    "html-webpack-plugin": "^5.6.0",
    "mini-css-extract-plugin": "^2.7.7",
    "postcss": "^8.4.33",
    "postcss-loader": "^8.1.0",
    "style-loader": "^3.3.4",
    "tailwindcss": "^3.4.1",
    "ts-loader": "^9.5.1",
    "typescript": "^5.3.3",
    "vitest": "^1.2.0",
    "@testing-library/react": "^14.1.2",
    "webpack": "^5.90.0",
    "webpack-cli": "^5.1.4",
    "webpack-dev-server": "^4.15.2",
    "webpack-merge": "^5.10.0"
  }
}
```

- [ ] **Step 4: Create apps/ai-workflow/tsconfig.json**

```json
{
  "extends": "../../tsconfig.base.json",
  "compilerOptions": {
    "outDir": "./dist",
    "rootDir": "./src",
    "jsx": "react-jsx"
  },
  "include": ["src/**/*.ts", "src/**/*.tsx"],
  "references": [{ "path": "../../packages/shared" }, { "path": "../../packages/micro-core" }]
}
```

- [ ] **Step 5: Create apps/ai-workflow/webpack/webpack.common.js**

```js
const path = require('path');
const HtmlWebpackPlugin = require('html-webpack-plugin');
const MiniCssExtractPlugin = require('mini-css-extract-plugin');

const isDev = process.env.NODE_ENV === 'development';
const appName = 'ai-workflow';

module.exports = {
  entry: path.resolve(__dirname, '../src/main.tsx'),
  output: {
    path: path.resolve(__dirname, '../dist'),
    filename: 'js/[name].[contenthash:8].js',
    library: `${appName}-[name]`,
    libraryTarget: 'umd',
    globalObject: 'window',
    publicPath: isDev ? '//localhost:8003/' : `/`,
  },
  resolve: {
    extensions: ['.tsx', '.ts', '.jsx', '.js', '.json'],
    alias: {
      '@': path.resolve(__dirname, '../src'),
      '@ai-design/shared': path.resolve(__dirname, '../../../packages/shared/src'),
      '@ai-design/micro-core': path.resolve(__dirname, '../../../packages/micro-core/src'),
    },
  },
  module: {
    rules: [
      {
        test: /\.tsx?$/,
        use: {
          loader: 'ts-loader',
          options: { transpileOnly: true },
        },
        exclude: /node_modules/,
      },
      {
        test: /\.css$/,
        oneOf: [
          {
            resourceQuery: /module/,
            use: [
              isDev ? 'style-loader' : MiniCssExtractPlugin.loader,
              {
                loader: 'css-loader',
                options: { modules: { localIdentName: '[local]_[hash:base64:8]' } },
              },
              'postcss-loader',
            ],
          },
          {
            use: [
              isDev ? 'style-loader' : MiniCssExtractPlugin.loader,
              'css-loader',
              'postcss-loader',
            ],
          },
        ],
      },
      {
        test: /\.(png|jpe?g|gif|svg|webp)$/i,
        type: 'asset/resource',
      },
      {
        test: /\.(woff2?|eot|ttf|otf)$/i,
        type: 'asset/resource',
      },
    ],
  },
  plugins: [
    new HtmlWebpackPlugin({
      template: path.resolve(__dirname, '../public/index.html'),
      title: 'AI Workflow',
    }),
    ...(isDev ? [] : [new MiniCssExtractPlugin({ filename: 'css/[name].[contenthash:8].css' })]),
  ],
};
```

- [ ] **Step 6: Create apps/ai-workflow/webpack/webpack.dev.js**

```js
const { merge } = require('webpack-merge');
const common = require('./webpack.common');

module.exports = merge(common, {
  mode: 'development',
  devtool: 'eval-cheap-module-source-map',
  devServer: {
    port: 8003,
    hot: true,
    open: false,
    historyApiFallback: true,
    headers: {
      'Access-Control-Allow-Origin': '*',
    },
  },
});
```

- [ ] **Step 7: Create apps/ai-workflow/webpack/webpack.prod.js**

```js
const { merge } = require('webpack-merge');
const common = require('./webpack.common');

module.exports = merge(common, {
  mode: 'production',
  devtool: 'source-map',
});
```

- [ ] **Step 8: Create apps/ai-workflow/postcss.config.js**

```js
module.exports = {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
};
```

- [ ] **Step 9: Create apps/ai-workflow/tailwind.config.js**

```js
/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./src/**/*.{tsx,ts,jsx,js}', './public/index.html'],
  theme: { extend: {} },
  plugins: [],
};
```

- [ ] **Step 10: Create apps/ai-workflow/public/index.html**

```html
<!DOCTYPE html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>AI Workflow</title>
  </head>
  <body>
    <div id="app"></div>
  </body>
</html>
```

- [ ] **Step 11: Create apps/ai-workflow/src/store/slices/workflowSlice.ts**

```ts
import { createSlice, type PayloadAction } from '@reduxjs/toolkit';

export interface Workflow {
  id: string;
  name: string;
  status: 'draft' | 'running' | 'completed' | 'failed';
}

export interface WorkflowState {
  loading: boolean;
  workflows: Workflow[];
}

export const initialState: WorkflowState = {
  loading: false,
  workflows: [],
};

const workflowSlice = createSlice({
  name: 'workflow',
  initialState,
  reducers: {
    setLoading(state, action: PayloadAction<boolean>) {
      state.loading = action.payload;
    },
    setWorkflows(state, action: PayloadAction<Workflow[]>) {
      state.workflows = action.payload;
    },
    addWorkflow(state, action: PayloadAction<Workflow>) {
      state.workflows.push(action.payload);
    },
  },
});

export const { setLoading, setWorkflows, addWorkflow } = workflowSlice.actions;
export default workflowSlice.reducer;
```

- [ ] **Step 12: Create apps/ai-workflow/src/store/index.ts**

```ts
import { configureStore } from '@reduxjs/toolkit';
import workflowReducer from './slices/workflowSlice';

export const store = configureStore({
  reducer: {
    workflow: workflowReducer,
  },
});

export type RootState = ReturnType<typeof store.getState>;
export type AppDispatch = typeof store.dispatch;
```

- [ ] **Step 13: Create apps/ai-workflow/src/router/index.tsx**

```tsx
import Home from '../pages/Home';
import About from '../pages/About';

export interface RouteConfig {
  path: string;
  element: React.ReactElement;
  label: string;
}

export const routes: RouteConfig[] = [
  { path: '/', element: <Home />, label: 'Home' },
  { path: '/about', element: <About />, label: 'About' },
];
```

- [ ] **Step 14: Create apps/ai-workflow/src/main.tsx** (qiankun lifecycle)

```tsx
import React from 'react';
import ReactDOM from 'react-dom/client';
import { Provider } from 'react-redux';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import { store } from './store';
import './styles/global.css';

let root: ReactDOM.Root | null = null;

function render(props: Record<string, unknown> = {}): void {
  const container = (props.container as HTMLElement) || document.getElementById('app');
  if (!container) return;

  const isQiankun = !!(window as unknown as Record<string, unknown>).__POWERED_BY_QIANKUN__;

  root = ReactDOM.createRoot(container.querySelector('#app') || container);
  root.render(
    <React.StrictMode>
      <Provider store={store}>
        <BrowserRouter basename={isQiankun ? '/ai-workflow' : '/'}>
          <App />
        </BrowserRouter>
      </Provider>
    </React.StrictMode>,
  );
}

function unmount(): void {
  root?.unmount();
  root = null;
}

if (!(window as unknown as Record<string, unknown>).__POWERED_BY_QIANKUN__) {
  render();
}

export async function bootstrap(): Promise<void> {
  console.log('[ai-workflow] bootstrap');
}

export async function mount(props: Record<string, unknown>): Promise<void> {
  console.log('[ai-workflow] mount', props);
  render(props);
}

export async function unmount(_props: Record<string, unknown>): Promise<void> {
  console.log('[ai-workflow] unmount');
  unmount();
}
```

- [ ] **Step 15: Create apps/ai-workflow/src/App.tsx**

```tsx
import React from 'react';
import { Routes, Route, NavLink } from 'react-router-dom';
import { routes } from './router';
import { onGlobalStateChange } from '@ai-design/micro-core';

const App: React.FC = () => {
  React.useEffect(() => {
    const cleanup = onGlobalStateChange((state, prev) => {
      console.log('[ai-workflow] global state changed:', state, prev);
    });
    return cleanup;
  }, []);

  return (
    <div className="ai-workflow p-6">
      <h1 className="text-2xl font-bold text-gray-800 mb-4">AI 工作流</h1>
      <nav className="flex space-x-4 mb-6">
        <NavLink
          to="/"
          className={({ isActive }) =>
            `text-blue-600 hover:underline ${isActive ? 'font-bold' : ''}`
          }
        >
          首页
        </NavLink>
        <NavLink
          to="/about"
          className={({ isActive }) =>
            `text-blue-600 hover:underline ${isActive ? 'font-bold' : ''}`
          }
        >
          关于
        </NavLink>
      </nav>
      <Routes>
        {routes.map((route) => (
          <Route key={route.path} path={route.path} element={route.element} />
        ))}
      </Routes>
    </div>
  );
};

export default App;
```

- [ ] **Step 16: Create apps/ai-workflow/src/pages/Home.tsx**

```tsx
import React from 'react';
import { useSelector } from 'react-redux';
import type { RootState } from '../store';

const Home: React.FC = () => {
  const loading = useSelector((state: RootState) => state.workflow.loading);

  return (
    <div className="bg-white rounded-lg shadow p-6">
      <p className="text-gray-600">欢迎使用 AI 工作流功能</p>
      {loading && <p className="text-blue-500 mt-2">加载中...</p>}
    </div>
  );
};

export default Home;
```

- [ ] **Step 17: Create apps/ai-workflow/src/pages/About.tsx**

```tsx
import React from 'react';

const About: React.FC = () => {
  return (
    <div className="bg-white rounded-lg shadow p-6">
      <p className="text-gray-600">AI 工作流子应用 v0.0.0</p>
      <p className="text-gray-400 text-sm mt-2">Powered by React + Redux Toolkit</p>
    </div>
  );
};

export default About;
```

- [ ] **Step 18: Create apps/ai-workflow/src/styles/global.css**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

body {
  margin: 0;
  padding: 0;
}
```

- [ ] **Step 19: Install dependencies**

```bash
cd apps/ai-workflow && pnpm install
```

- [ ] **Step 20: Run tests to verify they pass**

```bash
cd apps/ai-workflow && pnpm test
```

Expected: 2 tests PASS.

- [ ] **Step 21: Build**

```bash
cd apps/ai-workflow && pnpm build
```

Expected: Build succeeds.

- [ ] **Step 22: Commit**

```bash
git add apps/ai-workflow/ pnpm-lock.yaml
git commit -m "feat: scaffold ai-workflow with React + TS + Redux Toolkit + Webpack"
```

---

## Phase 8: Base App Route & Micro-App Container Integration

### Task 8.1: Add router, layout, and sub-app containers to main

**Files:**

- Create: `apps/main/src/router/index.ts`
- Create: `apps/main/src/views/Home.vue`
- Create: `apps/main/src/views/NotFound.vue`
- Create: `apps/main/src/layouts/SubAppContainer.vue`
- Modify: `apps/main/src/App.vue`

- [ ] **Step 1: Write failing test for main router**

Create `apps/main/__tests__/router.test.ts`:

```ts
import { describe, it, expect } from 'vitest';
import { routes } from '../src/router';

describe('main app routes', () => {
  it('should have Home, SubApp, and NotFound routes', () => {
    const names = routes.map((r) => r.name);
    expect(names).toContain('Home');
    expect(names).toContain('AiChat');
    expect(names).toContain('AiGeneration');
    expect(names).toContain('AiWorkflow');
    expect(names).toContain('NotFound');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd apps/main && npx vitest run
```

Expected: FAIL — module not found.

- [ ] **Step 3: Create apps/main/src/router/index.ts**

```ts
import type { RouteRecordRaw } from 'vue-router';
import Home from '../views/Home.vue';
import NotFound from '../views/NotFound.vue';
import SubAppContainer from '../layouts/SubAppContainer.vue';

export const routes: RouteRecordRaw[] = [
  {
    path: '/',
    name: 'Home',
    component: Home,
  },
  {
    path: '/ai-chat/:pathMatch(.*)*',
    name: 'AiChat',
    component: SubAppContainer,
    props: { containerId: 'sub-app-chat' },
  },
  {
    path: '/ai-generation/:pathMatch(.*)*',
    name: 'AiGeneration',
    component: SubAppContainer,
    props: { containerId: 'sub-app-generation' },
  },
  {
    path: '/ai-workflow/:pathMatch(.*)*',
    name: 'AiWorkflow',
    component: SubAppContainer,
    props: { containerId: 'sub-app-workflow' },
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'NotFound',
    component: NotFound,
  },
];
```

- [ ] **Step 4: Create apps/main/src/layouts/SubAppContainer.vue**

```vue
<template>
  <div :id="containerId" class="sub-app-container min-h-full"></div>
</template>

<script setup lang="ts">
defineProps<{
  containerId: string;
}>();
</script>

<style scoped>
.sub-app-container {
  /* Ensure sub-app container is always present for qiankun to mount into */
  min-height: 400px;
}
</style>
```

- [ ] **Step 5: Create apps/main/src/views/Home.vue**

```vue
<template>
  <div class="bg-white rounded-lg shadow p-8">
    <h2 class="text-xl font-semibold text-gray-800 mb-4">欢迎使用 AI Design Platform</h2>
    <p class="text-gray-600 mb-4">选择一个子应用开始使用：</p>
    <div class="grid grid-cols-3 gap-4">
      <router-link
        to="/ai-chat"
        class="block p-6 border rounded-lg hover:border-blue-500 hover:shadow-md transition-all"
      >
        <h3 class="font-semibold text-lg mb-2">💬 AI 对话</h3>
        <p class="text-sm text-gray-500">智能对话与交互</p>
      </router-link>
      <router-link
        to="/ai-generation"
        class="block p-6 border rounded-lg hover:border-green-500 hover:shadow-md transition-all"
      >
        <h3 class="font-semibold text-lg mb-2">🎨 AI 生成</h3>
        <p class="text-sm text-gray-500">内容与图像生成</p>
      </router-link>
      <router-link
        to="/ai-workflow"
        class="block p-6 border rounded-lg hover:border-purple-500 hover:shadow-md transition-all"
      >
        <h3 class="font-semibold text-lg mb-2">⚡ AI 工作流</h3>
        <p class="text-sm text-gray-500">自动化工作流编排</p>
      </router-link>
    </div>
  </div>
</template>
```

- [ ] **Step 6: Create apps/main/src/views/NotFound.vue**

```vue
<template>
  <div class="flex flex-col items-center justify-center py-20">
    <h2 class="text-4xl font-bold text-gray-300 mb-4">404</h2>
    <p class="text-gray-500 mb-6">页面不存在</p>
    <router-link to="/" class="text-blue-600 hover:underline">返回首页</router-link>
  </div>
</template>
```

- [ ] **Step 7: Modify apps/main/src/App.vue** — add router-view for route dispatch

Read the existing `apps/main/src/App.vue`, replace with:

```vue
<template>
  <div id="main-app" class="flex h-screen bg-gray-50">
    <aside class="w-60 bg-gray-900 text-white flex flex-col">
      <div class="px-6 py-4 text-lg font-bold border-b border-gray-700">AI Design</div>
      <nav class="flex-1 px-4 py-4 space-y-1">
        <router-link
          to="/"
          class="block px-3 py-2 rounded text-sm hover:bg-gray-700 transition-colors"
          active-class="bg-gray-700"
        >
          首页
        </router-link>
        <router-link
          to="/ai-chat"
          class="block px-3 py-2 rounded text-sm hover:bg-gray-700 transition-colors"
          active-class="bg-gray-700"
        >
          AI 对话
        </router-link>
        <router-link
          to="/ai-generation"
          class="block px-3 py-2 rounded text-sm hover:bg-gray-700 transition-colors"
          active-class="bg-gray-700"
        >
          AI 生成
        </router-link>
        <router-link
          to="/ai-workflow"
          class="block px-3 py-2 rounded text-sm hover:bg-gray-700 transition-colors"
          active-class="bg-gray-700"
        >
          AI 工作流
        </router-link>
      </nav>
    </aside>

    <main class="flex-1 flex flex-col overflow-hidden">
      <header class="h-14 border-b bg-white flex items-center px-6 shadow-sm">
        <span class="text-sm text-gray-500">AI Design Platform v0.0.0</span>
      </header>

      <div class="flex-1 overflow-auto p-6">
        <router-view />
      </div>
    </main>
  </div>
</template>

<script setup lang="ts"></script>
```

- [ ] **Step 8: Update apps/main/src/main.ts** — add router

```ts
import { createApp } from 'vue';
import { createPinia } from 'pinia';
import { createRouter, createWebHistory } from 'vue-router';
import App from './App.vue';
import { routes } from './router';
import { setupMicroApps, getAppConfigs } from '@ai-design/micro-core';
import './styles/global.css';

function bootstrap(): void {
  const app = createApp(App);
  const pinia = createPinia();
  const router = createRouter({
    history: createWebHistory(),
    routes,
  });

  app.use(pinia);
  app.use(router);
  app.mount('#app');

  // After Vue is mounted, register and start qiankun sub-apps
  setupMicroApps(getAppConfigs());
}

bootstrap();
```

- [ ] **Step 9: Add vitest to main for testing**

```bash
cd apps/main && pnpm add -D vitest @vue/test-utils happy-dom
```

- [ ] **Step 10: Add test config to main's package.json**

Read `apps/main/package.json`, add to scripts:

```json
"test": "vitest run",
"test:watch": "vitest"
```

And add vitest config at top level of package.json:

```json
"vitest": {
  "environment": "happy-dom"
}
```

- [ ] **Step 11: Run tests**

```bash
cd apps/main && pnpm test
```

Expected: Tests PASS.

- [ ] **Step 12: Commit**

```bash
git add apps/main/ pnpm-lock.yaml
git commit -m "feat: add router, sub-app containers, and views to main app"
```

---

## Phase 9: Cross-App Communication Verification

### Task 9.1: Add communication test to micro-core

**Files:**

- Modify: `packages/micro-core/__tests__/apps-config.test.ts` — add communication mocks
- Create: `packages/micro-core/__tests__/communication.test.ts`

- [ ] **Step 1: Write communication tests**

Create `packages/micro-core/__tests__/communication.test.ts`:

```ts
import { describe, it, expect, vi } from 'vitest';

// Mock qiankun globals before importing the module
vi.mock('qiankun', () => {
  const listeners: Array<(state: unknown, prevState: unknown) => void> = [];
  return {
    initGlobalState: vi.fn((initialState: unknown) => ({
      onGlobalStateChange: vi.fn(
        (callback: (state: unknown, prevState: unknown) => void, fireImmediately?: boolean) => {
          listeners.push(callback);
          if (fireImmediately) {
            callback(initialState, initialState);
          }
        },
      ),
      setGlobalState: vi.fn((newState: unknown) => {
        const prev = { ...initialState };
        Object.assign(initialState as Record<string, unknown>, newState as Record<string, unknown>);
        listeners.forEach((cb) => cb(initialState, prev));
      }),
      offGlobalStateChange: vi.fn(() => {
        listeners.length = 0;
      }),
    })),
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
    // Should not throw
    expect(() => initCommunication()).not.toThrow();
    // Second call should be no-op
    expect(() => initCommunication()).not.toThrow();
  });

  it('onGlobalStateChange should register a callback', () => {
    const callback = vi.fn();
    // This will trigger fireImmediately=false but still work
    expect(() => onGlobalStateChange(callback, false)).not.toThrow();
  });

  it('setGlobalState should call listeners', () => {
    const callback = vi.fn();
    onGlobalStateChange(callback, false);
    setGlobalState({ user: { id: '1', name: 'Test' } });
    // The mock qiankun setGlobalState calls all listeners
    expect(callback).toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run tests to verify**

```bash
cd packages/micro-core && pnpm test
```

Expected: Tests PASS.

- [ ] **Step 3: Commit**

```bash
git add packages/micro-core/
git commit -m "test: add communication module tests"
```

---

## Phase 10: Final Integration Verification

### Task 10.1: Full project validation

- [ ] **Step 1: Run all builds from root**

```bash
pnpm build
```

Expected: All 4 apps build successfully. Check output:

- `apps/main/dist/`
- `apps/ai-chat-app/dist/`
- `apps/ai-generation-app/dist/`
- `apps/ai-workflow/dist/`

- [ ] **Step 2: Run all lint checks from root**

```bash
pnpm lint
```

Expected: Zero lint errors (or only warnings).

- [ ] **Step 3: Run format check**

```bash
pnpm format:check
```

Expected: All files pass formatting check.

- [ ] **Step 4: Verify husky hooks are active**

```bash
ls -la .husky/
```

Expected: `pre-commit` and `commit-msg` files exist.

- [ ] **Step 5: Test commitlint with an invalid message (should fail)**

```bash
echo "bad commit message" | npx commitlint
```

Expected: Exit code non-zero (validation fails).

- [ ] **Step 6: Test commitlint with a valid message (should pass)**

```bash
echo "feat: add cross-app communication test" | npx commitlint
```

Expected: Exit code 0 (validation passes).

- [ ] **Step 7: Final commit**

```bash
git add -A
git commit -m "chore: final integration verification and cleanup"
```

---

## Summary

| Phase | Description                           | Files Created       |
| ----- | ------------------------------------- | ------------------- |
| 1     | Monorepo Foundation                   | 5                   |
| 2     | Code Standards Toolchain              | 7                   |
| 3     | packages/shared + packages/micro-core | 22                  |
| 4     | Base App (main)                       | 12                  |
| 5     | Sub-app 1 (ai-chat-app)               | 15                  |
| 6     | Sub-app 2 (ai-generation-app)         | 15                  |
| 7     | Sub-app 3 (ai-workflow)               | 17                  |
| 8     | Base app route integration            | 5                   |
| 9     | Communication verification            | 2                   |
| 10    | Final integration                     | 0 (validation only) |

**Total:** ~100 files across 10 phases, 3 shared packages, and 4 applications.
