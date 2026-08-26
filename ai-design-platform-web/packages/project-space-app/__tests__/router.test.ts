import { describe, expect, it } from 'vitest';
import { createMemoryHistory, createRouter } from 'vue-router';
import { PATHS, routes, ROUTE_NAMES } from '../src/router';
import { buildBreadcrumb } from '../src/router/breadcrumb';
import { SIDE_MENU_ITEMS } from '../src/layouts/menu';

async function createTestRouter() {
  const router = createRouter({ history: createMemoryHistory(), routes });
  await router.push('/');
  await router.isReady();
  return router;
}

describe('project-space routes', () => {
  it('defines five route records (redirect + four pages)', () => {
    expect(routes).toHaveLength(5);
  });

  it('redirects the default route to personal', async () => {
    const router = await createTestRouter();
    expect(router.currentRoute.value.name).toBe(ROUTE_NAMES.PERSONAL);
  });

  it('resolves /personal', async () => {
    const router = await createTestRouter();
    await router.push('/personal');
    expect(router.currentRoute.value.name).toBe(ROUTE_NAMES.PERSONAL);
  });

  it('resolves /teams', async () => {
    const router = await createTestRouter();
    await router.push('/teams');
    expect(router.currentRoute.value.name).toBe(ROUTE_NAMES.TEAMS);
  });

  it('resolves /teams/:teamId with the teamId param', async () => {
    const router = await createTestRouter();
    await router.push('/teams/team-1');
    expect(router.currentRoute.value.name).toBe(ROUTE_NAMES.TEAM_PROJECTS);
    expect(router.currentRoute.value.params.teamId).toBe('team-1');
  });

  it('resolves /projects/:id with the id param and source query', async () => {
    const router = await createTestRouter();
    await router.push('/projects/p1?from=team&teamId=team-1');
    expect(router.currentRoute.value.name).toBe(ROUTE_NAMES.PROJECT_DETAIL);
    expect(router.currentRoute.value.params.id).toBe('p1');
    expect(router.currentRoute.value.query).toEqual({ from: 'team', teamId: 'team-1' });
  });

  it('keeps menu and breadcrumb paths in sync with the route config (PATHS)', () => {
    const routePaths = routes.map((r) => r.path);

    // Every static PATHS constant is registered as a route path.
    expect(routePaths).toContain(PATHS.PERSONAL);
    expect(routePaths).toContain(PATHS.TEAMS);
    expect(routePaths).toContain(PATHS.TEAM_PROJECTS);
    expect(routePaths).toContain(PATHS.PROJECT_DETAIL);

    // Every side-menu key is a registered top-level route path.
    for (const item of SIDE_MENU_ITEMS) {
      expect(routePaths).toContain(item.key);
    }

    // Breadcrumb links are derived from the same constants.
    const personal = buildBreadcrumb({ name: ROUTE_NAMES.PERSONAL }, {}, {});
    expect(personal[1].path).toBe(PATHS.PERSONAL);

    const teams = buildBreadcrumb({ name: ROUTE_NAMES.TEAMS }, {}, {});
    expect(teams[1].path).toBe(PATHS.PERSONAL);

    const teamProjects = buildBreadcrumb(
      { name: ROUTE_NAMES.TEAM_PROJECTS },
      { teamId: 't1' },
      {},
      { teamName: 'T' },
    );
    expect(teamProjects[2].path).toBe(PATHS.TEAMS);

    const teamDetail = buildBreadcrumb(
      { name: ROUTE_NAMES.PROJECT_DETAIL },
      { id: 'p1' },
      { from: 'team', teamId: 't9' },
      { teamName: 'T', projectName: 'P' },
    );
    expect(teamDetail[2].path).toBe(PATHS.TEAMS);
    expect(teamDetail[3].path).toBe(PATHS.teamProjects('t9'));
  });

  it('fills route params through the PATHS factories', () => {
    expect(PATHS.teamProjects('abc')).toBe('/teams/abc');
    expect(PATHS.projectDetail('xyz')).toBe('/projects/xyz');
  });
});
