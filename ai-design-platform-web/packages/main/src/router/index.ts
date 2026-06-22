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
