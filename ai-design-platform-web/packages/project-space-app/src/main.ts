import './public-path';
import 'ant-design-vue/dist/reset.css';
import { createApp, type App as VueApp } from 'vue';
import { createPinia } from 'pinia';
import { createRouter, createWebHistory, type Router } from 'vue-router';
import App from './App.vue';
import { routes } from './router';
import { setAppRoot } from './portal-root';
import { installScopedCSSUpdateFix } from './style-isolation-fix';
import './styles/global.css';

let app: VueApp | null = null;
let router: Router | null = null;
let disconnectStyleFix: (() => void) | null = null;

function render(props: Record<string, unknown> = {}): void {
  const container = (props.container as HTMLElement) || document.getElementById('app');
  if (!container) return;

  app = createApp(App);
  const pinia = createPinia();

  router = createRouter({
    history: createWebHistory(
      (window as unknown as Record<string, unknown>).__POWERED_BY_QIANKUN__
        ? '/project-space'
        : '/',
    ),
    routes,
  });

  app.use(pinia);
  app.use(router);
  const mountEl = (container.querySelector('#app') as HTMLElement | null) || container;
  setAppRoot(mountEl);
  // Under qiankun the app wrapper (containing qiankun-head) is the parent of
  // the mount element; observe it to re-prefix cssinjs style updates.
  const observeRoot = mountEl.parentElement ?? mountEl;
  disconnectStyleFix = installScopedCSSUpdateFix(
    observeRoot,
    'div[data-qiankun="project-space-app"]',
  );
  app.mount(mountEl);
}

function destroy(): void {
  disconnectStyleFix?.();
  disconnectStyleFix = null;
  app?.unmount();
  app = null;
  router = null;
}

if (!(window as unknown as Record<string, unknown>).__POWERED_BY_QIANKUN__) {
  render();
}

export async function bootstrap(): Promise<void> {
  console.log('[project-space-app] bootstrap');
}

export async function mount(props: Record<string, unknown>): Promise<void> {
  console.log('[project-space-app] mount', props);
  render(props);
}

export async function unmount(_props: Record<string, unknown>): Promise<void> {
  console.log('[project-space-app] unmount');
  destroy();
}
