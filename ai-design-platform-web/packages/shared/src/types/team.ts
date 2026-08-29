/** 团队实体 — 对应 project-service Team */
export interface Team {
  id: string;
  name: string;
  description?: string;
  ownerId: string;
  createdAt: string;
}

/** 创建团队请求体 */
export interface CreateTeamRequest {
  name: string;
  description?: string;
}
