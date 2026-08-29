/** 项目级别:演示级 / 生产级 */
export type ProjectLevel = 'demo' | 'production';

/** 项目实体 — 个人项目 teamId 为 null,团队项目 teamId 为团队 id */
export interface Project {
  id: string;
  name: string;
  description?: string;
  level: ProjectLevel;
  teamId: string | null;
  createdBy: string;
  createdAt: string;
}

/** 创建项目请求体 — 不携带 teamId(或为 null)时创建个人项目 */
export interface CreateProjectRequest {
  name: string;
  description?: string;
  level: ProjectLevel;
  teamId?: string | null;
}
