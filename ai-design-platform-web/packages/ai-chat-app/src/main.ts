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

function destroy(): void {
  app?.unmount();
  app = null;
  router = null;
}

if (!(window as unknown as Record<string, unknown>).__POWERED_BY_QIANKUN__) {
  render();
}

export async function bootstrap(): Promise<void> {
  console.log('[ai-chat-app] bootstrap');
}

export async function mount(props: Record<string, unknown>): Promise<void> {
  console.log('[ai-chat-app] mount', props);
  render(props);
}

export async function unmount(_props: Record<string, unknown>): Promise<void> {
  console.log('[ai-chat-app] unmount');
  destroy();
}
