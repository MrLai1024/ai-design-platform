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
