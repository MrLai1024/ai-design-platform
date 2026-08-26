/**
 * Centralized route paths (relative to the sub-app base `/project-space` under
 * qiankun). Static values are the route patterns; the factory helpers produce
 * concrete paths with the params filled in — use them for all in-app
 * navigation so menu keys, breadcrumb links and router pushes never drift.
 *
 * Kept in its own module (re-exported by ./index) so views can import paths
 * without pulling in the router module and its view imports — avoids a
 * circular import between router/index.ts and the views.
 */
export const PATHS = {
  PERSONAL: '/personal',
  TEAMS: '/teams',
  TEAM_PROJECTS: '/teams/:teamId',
  PROJECT_DETAIL: '/projects/:id',
  /** Concrete path for a team's project list (fills the :teamId param) */
  teamProjects(teamId: string): string {
    return PATHS.TEAM_PROJECTS.replace(':teamId', teamId);
  },
  /** Concrete path for a project detail page (fills the :id param) */
  projectDetail(id: string): string {
    return PATHS.PROJECT_DETAIL.replace(':id', id);
  },
} as const;
