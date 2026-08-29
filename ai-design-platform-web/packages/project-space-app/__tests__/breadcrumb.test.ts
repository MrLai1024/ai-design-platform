import { describe, expect, it } from 'vitest';
import { buildBreadcrumb, HOME_PATH } from '../src/router/breadcrumb';
import { ROUTE_NAMES } from '../src/router';

const home = { label: '首页', path: HOME_PATH, external: true };
const projectSpace = { label: '项目空间', path: '/personal' };

describe('buildBreadcrumb — personal hierarchy', () => {
  it('personal page: 首页 / 项目空间 / 个人项目, last level is the current page', () => {
    const crumbs = buildBreadcrumb({ name: ROUTE_NAMES.PERSONAL }, {}, {});
    expect(crumbs).toEqual([
      home,
      projectSpace,
      { label: '个人项目' },
    ]);
  });

  it('project detail (personal source): 首页 / 项目空间 / 个人项目 / 项目名', () => {
    const crumbs = buildBreadcrumb(
      { name: ROUTE_NAMES.PROJECT_DETAIL },
      { id: 'p1' },
      {},
      { projectName: '演示项目' },
    );
    expect(crumbs).toEqual([
      home,
      projectSpace,
      { label: '个人项目', path: '/personal' },
      { label: '演示项目' },
    ]);
  });

  it('project detail without names falls back to placeholder labels', () => {
    const crumbs = buildBreadcrumb({ name: ROUTE_NAMES.PROJECT_DETAIL }, { id: 'p1' }, {});
    expect(crumbs.map((c) => c.label)).toEqual(['首页', '项目空间', '个人项目', '项目']);
  });
});

describe('buildBreadcrumb — team hierarchy', () => {
  it('teams page: 首页 / 项目空间 / 团队项目', () => {
    const crumbs = buildBreadcrumb({ name: ROUTE_NAMES.TEAMS }, {}, {});
    expect(crumbs).toEqual([
      home,
      projectSpace,
      { label: '团队项目' },
    ]);
  });

  it('team projects page: 首页 / 项目空间 / 团队项目 / 团队名, 团队项目 is clickable', () => {
    const crumbs = buildBreadcrumb(
      { name: ROUTE_NAMES.TEAM_PROJECTS },
      { teamId: 't1' },
      {},
      { teamName: '星辰团队' },
    );
    expect(crumbs).toEqual([
      home,
      projectSpace,
      { label: '团队项目', path: '/teams' },
      { label: '星辰团队' },
    ]);
  });

  it('team projects page without team name falls back to 团队 placeholder', () => {
    const crumbs = buildBreadcrumb({ name: ROUTE_NAMES.TEAM_PROJECTS }, { teamId: 't1' }, {});
    expect(crumbs[3]).toEqual({ label: '团队' });
  });

  it('project detail with team source (?from=team&teamId=): five levels, team level links back to the team', () => {
    const crumbs = buildBreadcrumb(
      { name: ROUTE_NAMES.PROJECT_DETAIL },
      { id: 'p2' },
      { from: 'team', teamId: 't9' },
      { teamName: '星辰团队', projectName: '生产项目' },
    );
    expect(crumbs).toEqual([
      home,
      projectSpace,
      { label: '团队项目', path: '/teams' },
      { label: '星辰团队', path: '/teams/t9' },
      { label: '生产项目' },
    ]);
  });

  it('project detail with from=team but missing teamId: team name is not clickable', () => {
    const crumbs = buildBreadcrumb(
      { name: ROUTE_NAMES.PROJECT_DETAIL },
      { id: 'p2' },
      { from: 'team' },
      { teamName: '星辰团队', projectName: '生产项目' },
    );
    expect(crumbs.map((c) => c.label)).toEqual(['首页', '项目空间', '团队项目', '星辰团队', '生产项目']);
    expect(crumbs[3].path).toBeUndefined();
  });
});

describe('buildBreadcrumb — click targets', () => {
  it('首页 is an external link to the base app root', () => {
    const crumbs = buildBreadcrumb({ name: ROUTE_NAMES.PERSONAL }, {}, {});
    expect(crumbs[0]).toEqual({ label: '首页', path: '/', external: true });
  });

  it('项目空间 level links back to /project-space/personal via in-app path /personal', () => {
    const crumbs = buildBreadcrumb({ name: ROUTE_NAMES.TEAMS }, {}, {});
    expect(crumbs[1].path).toBe('/personal');
    expect(crumbs[1].external).toBeUndefined();
  });

  it('unknown route falls back to 首页 / 项目空间', () => {
    const crumbs = buildBreadcrumb({ name: 'Unknown' }, {}, {});
    expect(crumbs).toEqual([home, projectSpace]);
  });
});

describe('buildBreadcrumb — shared constants immutability', () => {
  it('shared crumb constants are frozen so consumers cannot mutate them', () => {
    const personal = buildBreadcrumb({ name: ROUTE_NAMES.PERSONAL }, {}, {});
    expect(Object.isFrozen(personal[0])).toBe(true); // HOME_ITEM
    expect(Object.isFrozen(personal[1])).toBe(true); // PROJECT_SPACE_ITEM

    const teamProjects = buildBreadcrumb({ name: ROUTE_NAMES.TEAM_PROJECTS }, { teamId: 't1' }, {});
    expect(Object.isFrozen(teamProjects[2])).toBe(true); // TEAMS_ITEM (clickable variant)

    const personalDetail = buildBreadcrumb({ name: ROUTE_NAMES.PROJECT_DETAIL }, { id: 'p1' }, {});
    expect(Object.isFrozen(personalDetail[2])).toBe(true); // PERSONAL_ITEM

    const teamDetail = buildBreadcrumb(
      { name: ROUTE_NAMES.PROJECT_DETAIL },
      { id: 'p1' },
      { from: 'team', teamId: 't9' },
      { teamName: 'T', projectName: 'P' },
    );
    expect(Object.isFrozen(teamDetail[2])).toBe(true); // TEAMS_ITEM in the team hierarchy
  });

  it('mutating a returned shared item throws instead of leaking into later calls', () => {
    const crumbs = buildBreadcrumb({ name: ROUTE_NAMES.PERSONAL }, {}, {});
    expect(() => {
      (crumbs[0] as { label: string }).label = '首页2';
    }).toThrow(TypeError);
    // Later builds are unaffected (still the original label).
    const again = buildBreadcrumb({ name: ROUTE_NAMES.PERSONAL }, {}, {});
    expect(again[0].label).toBe('首页');
  });
});
