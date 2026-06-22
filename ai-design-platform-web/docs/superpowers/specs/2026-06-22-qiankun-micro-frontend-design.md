# Qiankun Micro-Frontend Tech Base Design

## Overview

基于 qiankun 的 monorepo 微前端通用技术底座。采用基座路由分发 + 子应用自治路由 + 全局事件总线通信 + 单共享包架构。

## Architecture Decisions

| Dimension                     | Selection                                            | Rationale                                    |
| ----------------------------- | ---------------------------------------------------- | -------------------------------------------- |
| Micro-frontend framework      | qiankun                                              | 成熟稳定，生态完善                           |
| Monorepo tool                 | pnpm workspace                                       | 磁盘高效，workspace 协议原生支持             |
| Build tool                    | Webpack 5                                            | qiankun 原生搭配，沙箱兼容性最好，工具链统一 |
| Base app                      | Vue3 + TS + Pinia                                    | 渐进式框架，组合式 API                       |
| Sub-app 1 (ai-chat-app)       | Vue3 + TS + Pinia                                    | 与基座技术栈一致                             |
| Sub-app 2 (ai-generation-app) | Vue3 + TS + Pinia                                    | 与基座技术栈一致                             |
| Sub-app 3 (ai-workflow)       | React + TS + Redux Toolkit                           | 异构验证，展示微前端多框架能力               |
| Styling                       | Tailwind CSS + PostCSS                               | 原子化 CSS，构建时 purging                   |
| Cross-app communication       | initGlobalState event bus                            | 轻量，适合跨应用状态同步                     |
| Routing                       | Base prefix dispatch + sub-app internal routing      | 解耦，子应用独立管理路由                     |
| Shared code                   | packages/shared + packages/micro-core                | 类型/工具/API 复用，qiankun 封装             |
| Code standards                | ESLint + Prettier + Husky + lint-staged + Commitlint | 全流程规范化                                 |

## Project Structure

```
ai-design-platform-web/
├── packages/
│   ├── shared/                    # Shared types, utils, API
│   │   ├── src/
│   │   │   ├── types/             # Global TS types
│   │   │   │   ├── global-state.ts
│   │   │   │   ├── api.ts
│   │   │   │   └── index.ts
│   │   │   ├── utils/
│   │   │   │   ├── format.ts
│   │   │   │   └── storage.ts
│   │   │   ├── api/
│   │   │   │   ├── request.ts     # axios instance + interceptors
│   │   │   │   └── index.ts
│   │   │   ├── constants/
│   │   │   │   ├── app-names.ts   # Sub-app name constants
│   │   │   │   ├── events.ts      # Global event name constants
│   │   │   │   └── index.ts
│   │   │   └── index.ts
│   │   └── package.json
│   └── micro-core/                # qiankun encapsulation layer
│       ├── src/
│       │   ├── apps-config.ts     # Sub-app registration manifest
│       │   ├── register.ts        # registerMicroApps + start
│       │   ├── lifecycle.ts       # Global lifecycle hooks
│       │   ├── communication.ts   # initGlobalState wrapper
│       │   ├── prefetch.ts        # Prefetch strategy
│       │   └── index.ts
│       └── package.json
├── apps/
│   ├── main/                      # Base app (Vue3 + TS + Pinia)
│   │   ├── src/
│   │   │   ├── layouts/           # Layout components
│   │   │   ├── router/            # Top-level route dispatch
│   │   │   ├── stores/            # Pinia stores
│   │   │   ├── views/             # Base-owned pages (home, 404)
│   │   │   ├── App.vue
│   │   │   └── main.ts            # Register micro-apps + bootstrap base
│   │   ├── webpack/
│   │   │   ├── webpack.common.js
│   │   │   ├── webpack.dev.js
│   │   │   └── webpack.prod.js
│   │   ├── tailwind.config.js
│   │   ├── postcss.config.js
│   │   ├── tsconfig.json
│   │   └── package.json
│   ├── ai-chat-app/               # Sub-app 1 (Vue3 + TS + Pinia)
│   │   ├── src/
│   │   │   ├── router/
│   │   │   ├── stores/
│   │   │   ├── views/
│   │   │   ├── App.vue
│   │   │   └── main.ts            # Export bootstrap/mount/unmount/update
│   │   ├── webpack/
│   │   │   ├── webpack.common.js
│   │   │   ├── webpack.dev.js
│   │   │   └── webpack.prod.js
│   │   ├── tailwind.config.js
│   │   ├── postcss.config.js
│   │   ├── tsconfig.json
│   │   └── package.json
│   ├── ai-generation-app/         # Sub-app 2 (Vue3 + TS + Pinia)
│   │   ├── src/                   # Same structure as ai-chat-app
│   │   │   ├── router/
│   │   │   ├── stores/
│   │   │   ├── views/
│   │   │   ├── App.vue
│   │   │   └── main.ts
│   │   ├── webpack/
│   │   │   ├── webpack.common.js
│   │   │   ├── webpack.dev.js
│   │   │   └── webpack.prod.js
│   │   ├── tailwind.config.js
│   │   ├── postcss.config.js
│   │   ├── tsconfig.json
│   │   └── package.json
│   └── ai-workflow/               # Sub-app 3 (React + TS + Redux Toolkit)
│       ├── src/
│       │   ├── router/
│       │   ├── store/             # Redux Toolkit slices
│       │   ├── pages/
│       │   ├── App.tsx
│       │   └── main.tsx           # Export bootstrap/mount/unmount/update
│       ├── webpack/
│       │   ├── webpack.common.js
│       │   ├── webpack.dev.js
│       │   └── webpack.prod.js
│       ├── tailwind.config.js
│       ├── postcss.config.js
│       ├── tsconfig.json
│       └── package.json
├── pnpm-workspace.yaml
├── .eslintrc.cjs
├── .prettierrc
├── .husky/
│   ├── pre-commit
│   └── commit-msg
├── commitlint.config.cjs
├── .lintstagedrc.cjs
├── tsconfig.base.json
├── package.json
└── README.md
```

## Routing & Communication

### Route Dispatch

| Browser URL        | Base Action                | Rendered Content                  |
| ------------------ | -------------------------- | --------------------------------- |
| `/`                | Base home page             | Base-owned page                   |
| `/ai-chat/*`       | Activate ai-chat-app       | ai-chat-app internal routes       |
| `/ai-generation/*` | Activate ai-generation-app | ai-generation-app internal routes |
| `/ai-workflow/*`   | Activate ai-workflow       | ai-workflow internal routes       |
| `/*`               | Base 404 page              | Base-owned page                   |

Base app registers sub-apps via `registerMicroApps` with `activeRule` set to path prefixes. Sub-apps manage their own internal routing via Vue Router or React Router.

### Cross-App Communication

Based on `initGlobalState` encapsulated in `packages/micro-core/src/communication.ts`:

- `onGlobalStateChange(callback, fireImmediately?)` — Listen for global state changes
- `setGlobalState(state)` — Update global state (triggers all listeners)
- `offGlobalStateChange()` — Remove listener

**Data flow:**

```
Base (data owner) ──setGlobalState──→ qiankun global state pool
                                          │
                ┌─────────────────────────┼─────────────────────────┐
                ↓                         ↓                         ↓
          ai-chat-app             ai-generation-app          ai-workflow
       onGlobalStateChange       onGlobalStateChange       onGlobalStateChange
```

**Typical use cases:**

- Base dispatches user info / tenant info → all sub-apps receive via `onGlobalStateChange`
- Cross-app notifications (e.g., "chat completed") → passed through event field in global state

### Event Name Convention

All global event names defined in `packages/shared/src/constants/events.ts`. Use constants instead of magic strings to prevent naming collisions.

## Shared Packages

### packages/shared

Shared types, utilities, and API layer consumed by base and all sub-apps.

- **types/**: `GlobalState`, API request/response generics
- **utils/**: Date/currency formatting, localStorage wrapper
- **api/**: Axios instance with interceptors (401 handling, unified error handling)
- **constants/**: App names, event names, path prefixes

### packages/micro-core

Qiankun encapsulation — provides plug-and-play micro-frontend capabilities.

- **apps-config.ts**: Sub-app registration manifest with dev/prod entry switching
- **register.ts**: `registerMicroApps(apps)` + `start(opts)` wrapper
- **lifecycle.ts**: Global `beforeLoad`, `afterMount`, `afterUnmount` hooks
- **communication.ts**: `initGlobalState` wrapper with event name whitelist
- **prefetch.ts**: Prefetch strategy configuration

## Build Configuration

### Webpack Setup

All four apps share the same webpack pattern:

- **webpack.common.js**: entry, output (UMD for sub-apps), resolve, loaders (ts, vue/react, css, postcss)
- **webpack.dev.js**: devServer, source-map, HMR
- **webpack.prod.js**: optimization, minification, output hashing

### Sub-app UMD Output

Each sub-app must output as UMD for qiankun dynamic loading:

```js
// webpack.common.js — sub-app output config
output: {
  library: `${appName}-[name]`,
  libraryTarget: 'umd',
  globalObject: 'window',
  publicPath: process.env.NODE_ENV === 'production'
    ? `//cdn.example.com/${appName}/`
    : `http://localhost:${port}/`
}
```

### Monorepo Dependency Resolution

Shared packages referenced via pnpm workspace protocol:

```json
// apps/ai-chat-app/package.json
{
  "dependencies": {
    "@ai-design/shared": "workspace:*",
    "@ai-design/micro-core": "workspace:*"
  }
}
```

Webpack `resolve.alias` configured to resolve `workspace:*` references correctly.

## Code Standards Pipeline

### Tools

| Tool        | Purpose                   | Config File                                    |
| ----------- | ------------------------- | ---------------------------------------------- |
| ESLint      | Code quality              | `.eslintrc.cjs` (root config, apps extend)     |
| Prettier    | Code formatting           | `.prettierrc` (unified rules)                  |
| Husky       | Git hooks manager         | `.husky/pre-commit`, `.husky/commit-msg`       |
| lint-staged | Staged files check        | `.lintstagedrc.cjs` (only changed files)       |
| Commitlint  | Commit message convention | `commitlint.config.cjs` (Conventional Commits) |

### Commit Pipeline

```
git commit -m "feat: add ai-chat module"
    │
    ▼
commit-msg hook → commitlint validates message format
    │
    ▼
pre-commit hook → lint-staged → ESLint + Prettier check staged files
    │
    ▼
Pass → commit succeeds / Fail → commit rejected
```

### Commit Convention

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat:      new feature
fix:       bug fix
refactor:  code refactoring
style:     formatting only
docs:      documentation
test:      test changes
chore:     build/config/tooling
```

## Development Workflow

### pnpm Scripts

```json
{
  "scripts": {
    "dev": "pnpm -r --parallel dev",
    "dev:main": "pnpm --filter main dev",
    "dev:chat": "pnpm --filter ai-chat-app dev",
    "dev:generation": "pnpm --filter ai-generation-app dev",
    "dev:workflow": "pnpm --filter ai-workflow dev",
    "build": "pnpm -r build",
    "lint": "pnpm -r lint",
    "format": "prettier --write .",
    "prepare": "husky install"
  }
}
```

### Day-to-Day Flow

1. `pnpm install` — Install all deps (workspace protocol auto-links shared packages)
2. `pnpm dev` — Start base + 3 sub-apps in parallel
   - main → `localhost:8000`
   - ai-chat-app → `localhost:8001`
   - ai-generation-app → `localhost:8002`
   - ai-workflow → `localhost:8003`
3. Visit `localhost:8000` — Base loads sub-apps by route
4. `git add` → `git commit` — husky + lint-staged intercepts automatically
5. `pnpm build` — Full production build

### pnpm-workspace.yaml

```yaml
packages:
  - 'apps/*'
  - 'packages/*'
```

### Port Allocation

| App               | Dev Port |
| ----------------- | -------- |
| main              | 8000     |
| ai-chat-app       | 8001     |
| ai-generation-app | 8002     |
| ai-workflow       | 8003     |

## Deployment Architecture

### Production Entry Configuration

Sub-app `entry` in `apps-config.ts` switches based on environment:

```ts
const ENTRY_MAP = {
  development: {
    'ai-chat-app': '//localhost:8001',
    'ai-generation-app': '//localhost:8002',
    'ai-workflow': '//localhost:8003',
  },
  production: {
    'ai-chat-app': '//cdn.example.com/ai-chat-app',
    'ai-generation-app': '//cdn.example.com/ai-generation-app',
    'ai-workflow': '//cdn.example.com/ai-workflow',
  },
};
```

### Production Build

1. `pnpm build` — Build all apps
2. Base app outputs standard JS
3. All sub-apps output UMD format
4. Static assets deployed to CDN with path matching production `entry` config
5. Base HTML entry deployed as main entry point

## Open Questions / Future Considerations

- CI/CD pipeline integration (Jenkins / GitHub Actions)
- Docker deployment configuration
- Micro-frontend monitoring and error tracking (Sentry integration)
- End-to-end testing strategy (Cypress / Playwright)
- Shared UI component library extraction from `packages/shared`
