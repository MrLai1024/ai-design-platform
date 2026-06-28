import type { RouteRecordRaw } from 'vue-router';
import ChatView from '../views/ChatView.vue';

export const routes: RouteRecordRaw[] = [
  { path: '/', name: 'Chat', component: ChatView },
  { path: '/chat', name: 'ChatNew', component: ChatView },
  { path: '/chat/:id', name: 'ChatDetail', component: ChatView },
];
