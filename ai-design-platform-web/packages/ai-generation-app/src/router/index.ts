import type { RouteRecordRaw } from 'vue-router'
import GenerationView from '../views/GenerationView.vue'

export const routes: RouteRecordRaw[] = [
  { path: '/', name: 'Generation', component: GenerationView },
]
