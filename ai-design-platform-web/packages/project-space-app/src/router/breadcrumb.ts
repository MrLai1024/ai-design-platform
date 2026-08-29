import { PATHS } from './paths';
import { ROUTE_NAMES } from './index';

/** Single breadcrumb level */
export interface BreadcrumbItem {
  label: string;
  /**
   * In-app route path, relative to the sub-app base (`/project-space` under
   * qiankun). Omitted for the current page (last level, not clickable).
   */
  path?: string;
  /**
   * When true the item navigates to the base app (main) instead of the in-app
   * router — used by 首页, which must go back to the base app root `/`.
   */
  external?: boolean;
}

/** Names resolved asynchronously after list/detail pages load (group 9) */
export interface BreadcrumbOptions {
  teamName?: string;
  projectName?: string;
}

/** Click target of the 首页 crumb — the base app root */
export const HOME_PATH = '/';

// Shared constants are frozen so consumers cannot mutate one crumb's label and
// leak the change into every other hierarchy built from the same instance.
const HOME_ITEM: BreadcrumbItem = Object.freeze({
  label: '首页',
  path: HOME_PATH,
  external: true,
});
const PROJECT_SPACE_ITEM: BreadcrumbItem = Object.freeze({ label: '项目空间', path: PATHS.PERSONAL });
const PERSONAL_ITEM: BreadcrumbItem = Object.freeze({ label: '个人项目', path: PATHS.PERSONAL });
const TEAMS_ITEM: BreadcrumbItem = Object.freeze({ label: '团队项目', path: PATHS.TEAMS });

/**
 * Derive the breadcrumb hierarchy from the matched route.
 *
 * - personal             → 首页 / 项目空间 / 个人项目
 * - teams                → 首页 / 项目空间 / 团队项目
 * - teams/:teamId        → 首页 / 项目空间 / 团队项目 / <团队名>
 * - projects/:id         → 首页 / 项目空间 / 个人项目 / <项目名>
 *                        → 首页 / 项目空间 / 团队项目 / <团队名> / <项目名>
 *                          (team source, `?from=team&teamId=<id>`)
 *
 * Team/project names are resolved asynchronously by AppLayout (via listTeams /
 * getProject) and passed in through `options`; until then placeholder labels
 * are used.
 */
export function buildBreadcrumb(
  route: { name?: string | symbol | null },
  params: Record<string, string>,
  query: Record<string, unknown>,
  options: BreadcrumbOptions = {},
): BreadcrumbItem[] {
  const { teamName = '团队', projectName = '项目' } = options;
  const name = typeof route.name === 'string' ? route.name : String(route.name ?? '');

  switch (name) {
    case ROUTE_NAMES.PERSONAL:
      return [HOME_ITEM, PROJECT_SPACE_ITEM, { label: '个人项目' }];
    case ROUTE_NAMES.TEAMS:
      return [HOME_ITEM, PROJECT_SPACE_ITEM, { label: '团队项目' }];
    case ROUTE_NAMES.TEAM_PROJECTS:
      return [HOME_ITEM, PROJECT_SPACE_ITEM, TEAMS_ITEM, { label: teamName }];
    case ROUTE_NAMES.PROJECT_DETAIL: {
      if (query.from === 'team') {
        const teamId = typeof query.teamId === 'string' ? query.teamId : undefined;
        const teamCrumb: BreadcrumbItem = teamId
          ? { label: teamName, path: PATHS.teamProjects(teamId) }
          : { label: teamName };
        return [HOME_ITEM, PROJECT_SPACE_ITEM, TEAMS_ITEM, teamCrumb, { label: projectName }];
      }
      return [HOME_ITEM, PROJECT_SPACE_ITEM, PERSONAL_ITEM, { label: projectName }];
    }
    default:
      return [HOME_ITEM, PROJECT_SPACE_ITEM];
  }
}
