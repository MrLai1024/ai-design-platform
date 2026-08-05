package handler

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"ai-design-platform/gateway/internal/client"

	"github.com/gin-gonic/gin"
)

// TestSubmitRuntimeFeedbackRoute — 路由 + 绑定校验冒烟测试：
// POST /api/v1/generation/runtime-feedback 已注册到 handler，且
// generation_id 缺失时在触碰 AI client 之前就返回 400（nil client 下
// 仍走通绑定层，证明路由/校验生效）。
func TestSubmitRuntimeFeedbackRoute(t *testing.T) {
	gin.SetMode(gin.TestMode)
	h := &E2EHandler{}

	r := gin.New()
	r.POST("/api/v1/generation/runtime-feedback", h.SubmitRuntimeFeedback)

	// 合法请求体但缺少 generation_id → 400，不触碰 AI client。
	body, _ := json.Marshal(RuntimeFeedbackRequest{Errors: []client.RuntimeError{}})
	req := httptest.NewRequest(http.MethodPost, "/api/v1/generation/runtime-feedback", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	if w.Code != http.StatusBadRequest {
		t.Fatalf("expected 400 for missing generation_id, got %d", w.Code)
	}
}

// TestSubmitRuntimeFeedbackParse — 非 JSON 请求体同样被绑定层 400 拦截。
func TestSubmitRuntimeFeedbackParse(t *testing.T) {
	gin.SetMode(gin.TestMode)
	h := &E2EHandler{}

	r := gin.New()
	r.POST("/api/v1/generation/runtime-feedback", h.SubmitRuntimeFeedback)

	req := httptest.NewRequest(http.MethodPost, "/api/v1/generation/runtime-feedback", bytes.NewReader([]byte("not json")))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	if w.Code != http.StatusBadRequest {
		t.Fatalf("expected 400 for malformed body, got %d", w.Code)
	}
}
