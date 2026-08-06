package handler

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"

	pb "ai-design-platform/gen/go/ai/v1"
	"ai-design-platform/gateway/internal/client"

	"github.com/gin-gonic/gin"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

// fakeFeedbackClient implements GraphAIClient (StreamGenerate unused by
// SubmitFeedback, stub only).
type fakeFeedbackClient struct {
	disp client.UserFeedbackDisposition
	err  error
}

func (f *fakeFeedbackClient) ReportUserFeedback(ctx context.Context, generationID, stage, feedback string) (client.UserFeedbackDisposition, error) {
	return f.disp, f.err
}

func (f *fakeFeedbackClient) StreamGenerate(ctx context.Context, req *pb.GenerateRequest) (pb.GenerationService_StreamGenerateClient, error) {
	return nil, nil
}

func postFeedback(t *testing.T, h *GraphSSEHandler, body string) *httptest.ResponseRecorder {
	t.Helper()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/generation/feedback", bytes.NewReader([]byte(body)))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	r := gin.New()
	r.POST("/api/v1/generation/feedback", h.SubmitFeedback)
	r.ServeHTTP(w, req)
	return w
}

// TestSubmitFeedbackMissingGenerationID — generation_id 缺失在触碰 AI client
// 之前就返回 400。
func TestSubmitFeedbackMissingGenerationID(t *testing.T) {
	gin.SetMode(gin.TestMode)
	h := &GraphSSEHandler{aiClient: nil, feedbackStore: map[string]string{}}

	w := postFeedback(t, h, `{"feedback": "改一下"}`)
	if w.Code != http.StatusBadRequest {
		t.Fatalf("expected 400 for missing generation_id, got %d", w.Code)
	}
}

// TestSubmitFeedbackUnknownGeneration404 — 无效 generation_id (从未服务过 +
// AI 服务无活跃 runner → gRPC NOT_FOUND) 映射 404。
func TestSubmitFeedbackUnknownGeneration404(t *testing.T) {
	gin.SetMode(gin.TestMode)
	h := &GraphSSEHandler{
		aiClient:      &fakeFeedbackClient{err: status.Error(codes.NotFound, "no runner")},
		feedbackStore: map[string]string{},
	}

	w := postFeedback(t, h, `{"generation_id": "ghost-gen", "stage": "code", "feedback": "改一下"}`)
	if w.Code != http.StatusNotFound {
		t.Fatalf("expected 404 for unknown generation_id, got %d (body=%s)", w.Code, w.Body.String())
	}
}

// TestSubmitFeedbackDeferredOnKnownGeneration — 曾服务过但 runner 丢失
// (如 ai-service 重启) → 200 deferred + feedbackStore 暂存 (下次流注入
// metadata code_feedback, ai-service 消费点兜底处置)。review fix。
func TestSubmitFeedbackDeferredOnKnownGeneration(t *testing.T) {
	gin.SetMode(gin.TestMode)
	h := &GraphSSEHandler{
		aiClient:        &fakeFeedbackClient{err: status.Error(codes.NotFound, "no runner")},
		feedbackStore:   map[string]string{},
		seenGenerations: map[string]bool{"gen-known": true},
	}

	w := postFeedback(t, h, `{"generation_id": "gen-known", "stage": "code", "feedback": "缺少订单列表组件"}`)
	if w.Code != http.StatusOK {
		t.Fatalf("expected 200 deferred, got %d (body=%s)", w.Code, w.Body.String())
	}
	var resp map[string]any
	if err := json.Unmarshal(w.Body.Bytes(), &resp); err != nil {
		t.Fatalf("invalid JSON response: %v", err)
	}
	if resp["received"] != true || resp["result"] != "deferred" {
		t.Fatalf("unexpected deferred payload: %v", resp)
	}
	if h.feedbackStore["gen-known"] != "缺少订单列表组件" {
		t.Fatalf("feedback not retained in feedbackStore for deferred injection")
	}
}

// TestRejectsScopeMarkerSync — 同步锚点 (review fix): Go 侧拒绝标记必须与
// ai-service recovery.py 的 REJECT_SCOPE_MARKERS 元组逐字一致 —
// ("重新生成", "取消", "重来", "不要") + 以「重新生成」开头的变体,
// 去除中英文标点后精确匹配。
func TestRejectsScopeMarkerSync(t *testing.T) {
	// 与 ai-service/app/services/generation/recovery.py REJECT_SCOPE_MARKERS
	// 保持同步 — 修改任一侧须同步另一侧并更新本测试。
	exact := []string{"重新生成", "取消", "重来", "不要"}
	variants := []string{"重新生成一遍", "重新生成吧", "重新生成！"}
	nonMatches := []string{"不要重复生成整个页面", "好的", "缺少订单列表组件", "生成一个页面", "别"}

	for _, m := range exact {
		if !rejectsScopeMarker(m) {
			t.Fatalf("rejectsScopeMarker(%q) = false, want true (must mirror REJECT_SCOPE_MARKERS)", m)
		}
	}
	for _, m := range variants {
		if !rejectsScopeMarker(m) {
			t.Fatalf("rejectsScopeMarker(%q) = false, want true (prefix variant)", m)
		}
	}
	for _, m := range nonMatches {
		if rejectsScopeMarker(m) {
			t.Fatalf("rejectsScopeMarker(%q) = true, want false", m)
		}
	}
	// 标点剥离与 Python 侧一致 (strip("。！!？?，,、 \t"))
	if !rejectsScopeMarker("取消。") || !rejectsScopeMarker(" 重来 ") {
		t.Fatalf("punctuation-trimmed markers must match")
	}
}

// TestSubmitFeedbackDisposition200 — 反馈进入 Manager 处置 → 200 + 处置结果。
func TestSubmitFeedbackDisposition200(t *testing.T) {
	gin.SetMode(gin.TestMode)
	h := &GraphSSEHandler{
		aiClient: &fakeFeedbackClient{disp: client.UserFeedbackDisposition{
			Category: "omission", CategoryLabel: "遗漏",
			Action: "重派功能实现任务（携带反馈）", Result: "dispatched", Reason: "需求已声明但未生成",
		}},
		feedbackStore: map[string]string{},
	}

	w := postFeedback(t, h, `{"generation_id": "gen-ok", "stage": "code", "feedback": "缺少订单列表组件"}`)
	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d (body=%s)", w.Code, w.Body.String())
	}
	var resp map[string]any
	if err := json.Unmarshal(w.Body.Bytes(), &resp); err != nil {
		t.Fatalf("invalid JSON response: %v", err)
	}
	if resp["received"] != true || resp["category"] != "omission" || resp["result"] != "dispatched" {
		t.Fatalf("unexpected disposition payload: %v", resp)
	}
}

// TestSubmitFeedbackScopeRejectMarker — 范围确认卡「重新生成/取消」拒绝标记
// 不进入 Manager 处置 (feedbackStore 注入, resume 侧 rejects_scope_change 消费)。
func TestSubmitFeedbackScopeRejectMarker(t *testing.T) {
	gin.SetMode(gin.TestMode)
	h := &GraphSSEHandler{aiClient: nil, feedbackStore: map[string]string{}}

	w := postFeedback(t, h, `{"generation_id": "gen-reject", "stage": "code", "feedback": "重新生成"}`)
	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}
	var resp map[string]any
	if err := json.Unmarshal(w.Body.Bytes(), &resp); err != nil {
		t.Fatalf("invalid JSON response: %v", err)
	}
	if resp["category"] != "scope_reject" {
		t.Fatalf("expected scope_reject short-circuit, got %v", resp)
	}
	// 反馈保留在 feedbackStore — 下一次同 generation 流注入 metadata。
	if h.feedbackStore["gen-reject"] != "重新生成" {
		t.Fatalf("scope-reject marker not retained in feedbackStore")
	}
}

// TestSubmitFeedbackRPCError502 — AI 服务不可用 → 502。
func TestSubmitFeedbackRPCError502(t *testing.T) {
	gin.SetMode(gin.TestMode)
	h := &GraphSSEHandler{
		aiClient:      &fakeFeedbackClient{err: errors.New("connection refused")},
		feedbackStore: map[string]string{},
	}

	w := postFeedback(t, h, `{"generation_id": "gen-err", "stage": "code", "feedback": "改一下"}`)
	if w.Code != http.StatusBadGateway {
		t.Fatalf("expected 502 on AI service error, got %d", w.Code)
	}
}
