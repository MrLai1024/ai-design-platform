package handler

import (
	"errors"
	"net/http"
	"strings"
	"time"

	"ai-design-platform/project-service/internal/middleware"
	"ai-design-platform/project-service/internal/store"

	"github.com/gin-gonic/gin"
)

// TeamHandler 提供团队列表/创建/搜索/加入接口。
type TeamHandler struct {
	teams *store.Teams
}

// NewTeamHandler 创建 TeamHandler。
func NewTeamHandler(teams *store.Teams) *TeamHandler {
	return &TeamHandler{teams: teams}
}

// teamJSON 是 Team 的对外响应体(camelCase,与前端契约一致)。
type teamJSON struct {
	ID          string    `json:"id"`
	Name        string    `json:"name"`
	Description *string   `json:"description,omitempty"`
	OwnerID     string    `json:"ownerId"`
	CreatedAt   time.Time `json:"createdAt"`
}

// toTeamJSON 将 store.Team 转为对外响应体。
func toTeamJSON(t store.Team) teamJSON {
	return teamJSON{
		ID:          t.ID,
		Name:        t.Name,
		Description: t.Description,
		OwnerID:     t.OwnerID,
		CreatedAt:   t.CreatedAt,
	}
}

// toTeamsJSON 批量转换,保证空列表序列化为 [] 而非 null。
func toTeamsJSON(teams []store.Team) []teamJSON {
	out := make([]teamJSON, 0, len(teams))
	for _, t := range teams {
		out = append(out, toTeamJSON(t))
	}
	return out
}

// currentUserID 从 context 取出认证中间件注入的用户 id;缺失时写 401 并返回 false。
func currentUserID(c *gin.Context) (string, bool) {
	// 中间件已保证 user_id 存在,这里只是防御性兜底。
	userID, ok := middleware.GetUserID(c)
	if !ok {
		Error(c, http.StatusUnauthorized, CodeUnauthorized, "未认证")
	}
	return userID, ok
}

// List 返回当前用户已加入的团队列表(GET /api/v1/users/me/teams)。
// 排序由 store 层保证(加入时间倒序)。
func (h *TeamHandler) List(c *gin.Context) {
	userID, ok := currentUserID(c)
	if !ok {
		return
	}
	teams, err := h.teams.ListByUser(c.Request.Context(), userID)
	if err != nil {
		internalError(c, "list teams", err)
		return
	}
	Success(c, http.StatusOK, toTeamsJSON(teams))
}

// createTeamRequest 是创建团队的请求体。
type createTeamRequest struct {
	Name        string `json:"name"`
	Description string `json:"description"`
}

// Create 创建团队并把创建者写入 team_members(POST /api/v1/teams)。
// 名称必填(去除首尾空白后非空),简介选填(空串落 NULL)。
func (h *TeamHandler) Create(c *gin.Context) {
	userID, ok := currentUserID(c)
	if !ok {
		return
	}
	var req createTeamRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		Error(c, http.StatusBadRequest, CodeParamError, "参数错误")
		return
	}
	req.Name = strings.TrimSpace(req.Name)
	req.Description = strings.TrimSpace(req.Description)
	if req.Name == "" {
		Error(c, http.StatusBadRequest, CodeParamError, "参数错误")
		return
	}
	team, err := h.teams.CreateTeam(c.Request.Context(), req.Name, req.Description, userID)
	if err != nil {
		internalError(c, "create team", err)
		return
	}
	Success(c, http.StatusCreated, toTeamJSON(team))
}

// Search 返回可加入团队列表:按名称模糊匹配、排除当前用户已加入的团队(GET /api/v1/teams?keyword=)。
// keyword 可选(去除首尾空白后非空才过滤;缺失/空白时返回全部未加入团队)。
// 无分页、通配符(%/_)不转义是有意取舍:团队总量小,搜索仅用于"加入团队"入口。
func (h *TeamHandler) Search(c *gin.Context) {
	userID, ok := currentUserID(c)
	if !ok {
		return
	}
	keyword := strings.TrimSpace(c.Query("keyword"))
	teams, err := h.teams.SearchByName(c.Request.Context(), keyword, userID)
	if err != nil {
		internalError(c, "search teams", err)
		return
	}
	Success(c, http.StatusOK, toTeamsJSON(teams))
}

// Join 加入团队(POST /api/v1/teams/:id/members)。
// 重复加入返回 409,团队不存在返回 404,非 UUID 的 :id 返回 400。
func (h *TeamHandler) Join(c *gin.Context) {
	userID, ok := currentUserID(c)
	if !ok {
		return
	}
	teamID, ok := parseUUIDParam(c, "id")
	if !ok {
		return
	}
	err := h.teams.JoinTeam(c.Request.Context(), teamID, userID)
	switch {
	case errors.Is(err, store.ErrMemberConflict):
		Error(c, http.StatusConflict, CodeConflict, "已加入该团队")
	case errors.Is(err, store.ErrTeamNotFound):
		Error(c, http.StatusNotFound, CodeNotFound, "团队不存在")
	case err != nil:
		internalError(c, "join team", err)
	default:
		Success(c, http.StatusOK, nil)
	}
}
