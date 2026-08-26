import { beforeEach, describe, expect, it, vi } from 'vitest';
import { http } from '../src/api/request';
import { autoRegister, getMe } from '../src/api/user';
import { createTeam, joinTeam, listTeams, searchTeams } from '../src/api/team';
import { createProject, getProject, listProjects, listTeamProjects } from '../src/api/project';
import { installCaptureAdapter, type CapturedRequest } from './helpers/http';
import { createLocalStorageMock } from './helpers/local-storage';

beforeEach(() => {
  vi.unstubAllGlobals();
  vi.stubGlobal('localStorage', createLocalStorageMock());
});

function captureNext(): CapturedRequest[] {
  const { calls, adapter } = installCaptureAdapter();
  http.defaults.adapter = adapter;
  return calls;
}

describe('user api', () => {
  it('autoRegister posts to /v1/auth/auto-register', async () => {
    const calls = captureNext();
    await autoRegister();
    expect(calls[0].method).toBe('post');
    expect(calls[0].url).toBe('/v1/auth/auto-register');
  });

  it('getMe gets /v1/auth/me', async () => {
    const calls = captureNext();
    await getMe();
    expect(calls[0].method).toBe('get');
    expect(calls[0].url).toBe('/v1/auth/me');
  });
});

describe('team api', () => {
  it('listTeams gets /v1/teams', async () => {
    const calls = captureNext();
    await listTeams();
    expect(calls[0].method).toBe('get');
    expect(calls[0].url).toBe('/v1/teams');
  });

  it('searchTeams gets /v1/teams/search with keyword param', async () => {
    const calls = captureNext();
    await searchTeams('设计');
    expect(calls[0].method).toBe('get');
    expect(calls[0].url).toBe('/v1/teams/search');
    expect(calls[0].params).toEqual({ keyword: '设计' });
  });

  it('createTeam posts /v1/teams with name/description body', async () => {
    const calls = captureNext();
    await createTeam({ name: '前端组', description: '前端团队' });
    expect(calls[0].method).toBe('post');
    expect(calls[0].url).toBe('/v1/teams');
    expect(JSON.parse(calls[0].data as string)).toEqual({ name: '前端组', description: '前端团队' });
  });

  it('joinTeam posts /v1/teams/:id/join', async () => {
    const calls = captureNext();
    await joinTeam('team-9');
    expect(calls[0].method).toBe('post');
    expect(calls[0].url).toBe('/v1/teams/team-9/join');
  });
});

describe('project api', () => {
  it('createProject posts /v1/projects with name/description/level/teamId', async () => {
    const calls = captureNext();
    await createProject({ name: '电商改版', description: '首页', level: 'production', teamId: 'team-1' });
    expect(calls[0].method).toBe('post');
    expect(calls[0].url).toBe('/v1/projects');
    expect(JSON.parse(calls[0].data as string)).toEqual({
      name: '电商改版',
      description: '首页',
      level: 'production',
      teamId: 'team-1',
    });
  });

  it('createProject omits teamId for personal projects', async () => {
    const calls = captureNext();
    await createProject({ name: '个人项目', level: 'demo' });
    const body = JSON.parse(calls[0].data as string);
    expect(body).toEqual({ name: '个人项目', level: 'demo' });
    expect('teamId' in body).toBe(false);
  });

  it('listProjects gets /v1/projects', async () => {
    const calls = captureNext();
    await listProjects();
    expect(calls[0].method).toBe('get');
    expect(calls[0].url).toBe('/v1/projects');
  });

  it('listTeamProjects gets /v1/teams/:teamId/projects', async () => {
    const calls = captureNext();
    await listTeamProjects('team-2');
    expect(calls[0].method).toBe('get');
    expect(calls[0].url).toBe('/v1/teams/team-2/projects');
  });

  it('getProject gets /v1/projects/:id', async () => {
    const calls = captureNext();
    await getProject('proj-1');
    expect(calls[0].method).toBe('get');
    expect(calls[0].url).toBe('/v1/projects/proj-1');
  });
});
