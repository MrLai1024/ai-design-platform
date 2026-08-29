import { get, post } from './request';
import type { CreateTeamRequest, Team } from '../types/team';

/**
 * 我的团队列表
 * GET /api/v1/users/me/teams → Team[]
 * (响应拦截器已解包 response.data,Promise 直接解析为响应体)
 */
export function listTeams(): Promise<Team[]> {
  return get<Team[]>('/v1/users/me/teams');
}

/**
 * 按名称搜索团队(排除当前用户已加入的团队;keyword 可选,为空时不带查询参数)
 * GET /api/v1/teams?keyword= → Team[]
 */
export function searchTeams(keyword: string): Promise<Team[]> {
  return get<Team[]>('/v1/teams', keyword ? { keyword } : undefined);
}

/**
 * 创建团队(创建者自动成为成员)
 * POST /api/v1/teams  body: { name, description? }
 */
export function createTeam(data: CreateTeamRequest): Promise<Team> {
  return post<Team>('/v1/teams', data);
}

/**
 * 加入团队(重复加入返回 409)
 * POST /api/v1/teams/:teamId/members
 */
export function joinTeam(teamId: string): Promise<void> {
  return post<void>(`/v1/teams/${teamId}/members`);
}
