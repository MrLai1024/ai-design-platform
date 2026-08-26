import type { RouteRecordRaw } from 'vue-router';
import PersonalView from '../views/PersonalView.vue';
import TeamsView from '../views/TeamsView.vue';
import TeamProjectsView from '../views/TeamProjectsView.vue';
import ProjectDetailView from '../views/ProjectDetailView.vue';
import { PATHS } from './paths';

export { PATHS } from './paths';

/** Route names — also used by the breadcrumb builder to derive hierarchy levels */
export const ROUTE_NAMES = {
  PERSONAL: 'Personal',
  TEAMS: 'Teams',
  TEAM_PROJECTS: 'TeamProjects',
  PROJECT_DETAIL: 'ProjectDetail',
} as const;

export type RouteName = (typeof ROUTE_NAMES)[keyof typeof ROUTE_NAMES];

/**
 * Sub-app routes. Under qiankun the router base is `/project-space`, so these
 * paths map to `/project-space/personal`, `/project-space/teams`, etc.
 */
export const routes: RouteRecordRaw[] = [
  { path: '/', redirect: PATHS.PERSONAL },
  { path: PATHS.PERSONAL, name: ROUTE_NAMES.PERSONAL, component: PersonalView },
  { path: PATHS.TEAMS, name: ROUTE_NAMES.TEAMS, component: TeamsView },
  {
    path: PATHS.TEAM_PROJECTS,
    name: ROUTE_NAMES.TEAM_PROJECTS,
    component: TeamProjectsView,
  },
  {
    path: PATHS.PROJECT_DETAIL,
    name: ROUTE_NAMES.PROJECT_DETAIL,
    component: ProjectDetailView,
  },
];
