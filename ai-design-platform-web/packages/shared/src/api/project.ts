import { get, post } from './request';
import type { CreateProjectRequest, Project } from '../types/project';

/**
 * 创建项目(无 teamId 为个人项目,有 teamId 为团队项目)
 * POST /api/v1/projects  body: { name, description?, level, teamId? }
 * (响应拦截器已解包 response.data,Promise 直接解析为响应体)
 */
export function createProject(data: CreateProjectRequest): Promise<Project> {
  return post<Project>('/v1/projects', data);
}

/**
 * 个人项目列表(team_id IS NULL)
 * GET /api/v1/projects → Project[]
 */
export function listProjects(): Promise<Project[]> {
  return get<Project[]>('/v1/projects');
}

/**
 * 团队项目列表(仅团队成员可见,非成员 403)
 * GET /api/v1/teams/:teamId/projects → Project[]
 */
export function listTeamProjects(teamId: string): Promise<Project[]> {
  return get<Project[]>(`/v1/teams/${teamId}/projects`);
}

/**
 * 项目详情(校验归属可见性)
 * GET /api/v1/projects/:projectId
 */
export function getProject(projectId: string): Promise<Project> {
  return get<Project>(`/v1/projects/${projectId}`);
}
