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
    path: '/ai-generation/:pathMatch(.*)*',
    name: 'AiGeneration',
    component: SubAppContainer,
    props: { containerId: 'sub-app-generation' },
  },
  {
    path: '/project-space/:pathMatch(.*)*',
    name: 'ProjectSpace',
    component: SubAppContainer,
    props: { containerId: 'sub-app-project-space' },
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'NotFound',
    component: NotFound,
  },
];
