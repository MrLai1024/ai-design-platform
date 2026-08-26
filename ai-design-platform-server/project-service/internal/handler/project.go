package handler

import (
	"errors"
	"net/http"
	"strings"
	"time"

	"ai-design-platform/project-service/internal/store"

	"github.com/gin-gonic/gin"
)

// ProjectHandler 提供项目创建/列表/详情接口。
type ProjectHandler struct {
	projects *store.Projects
}

// NewProjectHandler 创建 ProjectHandler。
func NewProjectHandler(projects *store.Projects) *ProjectHandler {
	return &ProjectHandler{projects: projects}
}

// projectJSON 是 Project 的对外响应体(camelCase,与前端契约一致)。
type projectJSON struct {
	ID          string    `json:"id"`
	Name        string    `json:"name"`
	Description *string   `json:"description,omitempty"`
	Level       string    `json:"level"`
	TeamID      *string   `json:"teamId"`
	CreatedBy   string    `json:"createdBy"`
	CreatedAt   time.Time `json:"createdAt"`
}

// toProjectJSON 将 store.Project 转为对外响应体。
func toProjectJSON(p store.Project) projectJSON {
	return projectJSON{
		ID:          p.ID,
		Name:        p.Name,
		Description: p.Description,
		Level:       p.Level,
		TeamID:      p.TeamID,
		CreatedBy:   p.CreatedBy,
		CreatedAt:   p.CreatedAt,
	}
}

// toProjectsJSON 批量转换,保证空列表序列化为 [] 而非 null。
func toProjectsJSON(projects []store.Project) []projectJSON {
	out := make([]projectJSON, 0, len(projects))
	for _, p := range projects {
		out = append(out, toProjectJSON(p))
	}
	return out
}

// createProjectRequest 是创建项目的请求体。TeamID 为 nil 表示个人项目。
type createProjectRequest struct {
	Name        string  `json:"name"`
	Description string  `json:"description"`
	Level       string  `json:"level"`
	TeamID      *string `json:"teamId"`
}

// Create 创建项目(POST /api/v1/projects)。
// 名称必填(去除首尾空白后非空),level 仅允许 demo/production;
// 无 teamId 落个人项目;有 teamId 时校验成员身份:团队不存在 404、非成员 403。
func (h *ProjectHandler) Create(c *gin.Context) {
	userID, ok := currentUserID(c)
	if !ok {
		return
	}
	var req createProjectRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		Error(c, http.StatusBadRequest, CodeParamError, "参数错误")
		return
	}
	req.Name = strings.TrimSpace(req.Name)
	req.Description = strings.TrimSpace(req.Description)
	req.Level = strings.TrimSpace(req.Level)
	if req.Name == "" {
		Error(c, http.StatusBadRequest, CodeParamError, "参数错误")
		return
	}
	if req.Level != "demo" && req.Level != "production" {
		Error(c, http.StatusBadRequest, CodeParamError, "参数错误")
		return
	}
	// teamId 非 UUID 时提前 400,避免进入 PostgreSQL uuid 列触发 22P02 而返回 500。
	if req.TeamID != nil && !uuidParamRe.MatchString(*req.TeamID) {
		Error(c, http.StatusBadRequest, CodeParamError, "参数错误")
		return
	}
	if req.TeamID != nil {
		member, err := h.projects.IsMember(c.Request.Context(), *req.TeamID, userID)
		switch {
		case errors.Is(err, store.ErrTeamNotFound):
			Error(c, http.StatusNotFound, CodeNotFound, "团队不存在")
			return
		case err != nil:
			internalError(c, "check team membership", err)
			return
		case !member:
			Error(c, http.StatusForbidden, CodeForbidden, "无权限")
			return
		}
	}
	project, err := h.projects.Create(c.Request.Context(), req.Name, req.Description, req.Level, req.TeamID, userID)
	if err != nil {
		internalError(c, "create project", err)
		return
	}
	Success(c, http.StatusCreated, toProjectJSON(project))
}

// List 返回当前用户创建的个人项目列表(GET /api/v1/users/me/projects,team_id IS NULL AND created_by=当前用户)。
// 排序由 store 层保证(创建时间倒序)。
func (h *ProjectHandler) List(c *gin.Context) {
	userID, ok := currentUserID(c)
	if !ok {
		return
	}
	projects, err := h.projects.ListPersonal(c.Request.Context(), userID)
	if err != nil {
		internalError(c, "list personal projects", err)
		return
	}
	Success(c, http.StatusOK, toProjectsJSON(projects))
}

// TeamProjects 返回团队项目列表(GET /api/v1/teams/:id/projects)。
// 团队不存在 404,非团队成员 403。
func (h *ProjectHandler) TeamProjects(c *gin.Context) {
	userID, ok := currentUserID(c)
	if !ok {
		return
	}
	teamID, ok := parseUUIDParam(c, "id")
	if !ok {
		return
	}
	member, err := h.projects.IsMember(c.Request.Context(), teamID, userID)
	switch {
	case errors.Is(err, store.ErrTeamNotFound):
		Error(c, http.StatusNotFound, CodeNotFound, "团队不存在")
		return
	case err != nil:
		internalError(c, "check team membership", err)
		return
	case !member:
		Error(c, http.StatusForbidden, CodeForbidden, "无权限")
		return
	}
	projects, err := h.projects.ListByTeam(c.Request.Context(), teamID)
	if err != nil {
		internalError(c, "list team projects", err)
		return
	}
	Success(c, http.StatusOK, toProjectsJSON(projects))
}

// Detail 返回项目详情(GET /api/v1/projects/:id)。
// 归属可见性:个人项目仅创建者、团队项目仅成员;无权访问返回 403,项目不存在返回 404。
// 403/404 区分(而非统一 404)让前端能区分"项目没了"与"没权限"两种提示。
func (h *ProjectHandler) Detail(c *gin.Context) {
	userID, ok := currentUserID(c)
	if !ok {
		return
	}
	projectID, ok := parseUUIDParam(c, "id")
	if !ok {
		return
	}
	project, err := h.projects.Get(c.Request.Context(), projectID)
	if errors.Is(err, store.ErrProjectNotFound) {
		Error(c, http.StatusNotFound, CodeNotFound, "项目不存在")
		return
	}
	if err != nil {
		internalError(c, "get project", err)
		return
	}
	if project.TeamID == nil {
		// 个人项目仅创建者可见。
		if project.CreatedBy != userID {
			Error(c, http.StatusForbidden, CodeForbidden, "无权限")
			return
		}
	} else {
		member, err := h.projects.IsMember(c.Request.Context(), *project.TeamID, userID)
		switch {
		case errors.Is(err, store.ErrTeamNotFound):
			// 团队项目引用的团队必然存在(外键约束),这里仅防御性兜底。
			Error(c, http.StatusNotFound, CodeNotFound, "项目不存在")
			return
		case err != nil:
			internalError(c, "check team membership", err)
			return
		case !member:
			Error(c, http.StatusForbidden, CodeForbidden, "无权限")
			return
		}
	}
	Success(c, http.StatusOK, toProjectJSON(project))
}
