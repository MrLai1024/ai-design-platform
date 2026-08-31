package handler

import (
	"encoding/json"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"ai-design-platform/gateway/internal/auth"
	"ai-design-platform/gateway/internal/middleware"

	"github.com/gin-gonic/gin"
)

// proxyTestUserID 是代理身份注入测试用的可信用户 id(与 JWT claims 一致)。
const proxyTestUserID = "11111111-1111-1111-1111-111111111111"

// newProxyRouter 装配一个只挂代理路由的 gin 引擎(无鉴权,与 main.go 相反顺序,
// 仅用于路径透传/覆盖/502 等与鉴权无关的行为测试)。
func newProxyRouter(t *testing.T, upstream string) *gin.Engine {
	t.Helper()
	gin.SetMode(gin.TestMode)
	proxy, err := NewProjectServiceProxy(upstream)
	if err != nil {
		t.Fatalf("NewProjectServiceProxy(%q): %v", upstream, err)
	}
	r := gin.New()
	proxy.Register(r)
	return r
}

// newProxyAuthedRouter 按 main.go 的真实装配顺序挂路由:先挂全局 Auth 再注册代理,
// 转发请求先经过 gateway 鉴权,Auth 注入的 user_id 由 Director 以 X-User-Id 传给上游。
func newProxyAuthedRouter(t *testing.T, upstream string) (*gin.Engine, *auth.Manager) {
	t.Helper()
	gin.SetMode(gin.TestMode)
	proxy, err := NewProjectServiceProxy(upstream)
	if err != nil {
		t.Fatalf("NewProjectServiceProxy(%q): %v", upstream, err)
	}
	tokens := auth.NewManager("test-secret")
	r := gin.New()
	r.Use(middleware.Auth(tokens))
	proxy.Register(r)
	return r, tokens
}

// startUpstream 启动一个伪 project-service,记录收到的请求并回显。
// 返回的 getter 用于读取最近一次收到的请求。
func startUpstream(t *testing.T) (*httptest.Server, func() *http.Request) {
	t.Helper()
	var lastReq *http.Request
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		lastReq = r.Clone(r.Context())
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusCreated)
		_, _ = io.WriteString(w, `{"ok":true}`)
	}))
	t.Cleanup(upstream.Close)
	return upstream, func() *http.Request { return lastReq }
}

// TestProjectServiceProxyPassthrough 验证路径/query/方法/Authorization 头与响应体透传。
func TestProjectServiceProxyPassthrough(t *testing.T) {
	upstream, getLastReq := startUpstream(t)
	r := newProxyRouter(t, upstream.URL)
	srv := httptest.NewServer(r)
	defer srv.Close()

	req, err := http.NewRequest(http.MethodPost, srv.URL+"/api/v1/teams?page=2", strings.NewReader(`{"name":"x"}`))
	if err != nil {
		t.Fatal(err)
	}
	req.Header.Set("Authorization", "Bearer test-token-123")
	req.Header.Set("Content-Type", "application/json")

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusCreated {
		t.Fatalf("status = %d, want %d", resp.StatusCode, http.StatusCreated)
	}
	body, _ := io.ReadAll(resp.Body)
	if string(body) != `{"ok":true}` {
		t.Fatalf("body = %q", body)
	}
	lastReq := getLastReq()
	if lastReq == nil {
		t.Fatal("upstream did not receive request")
	}
	if lastReq.Method != http.MethodPost {
		t.Errorf("upstream method = %s, want POST", lastReq.Method)
	}
	if lastReq.URL.Path != "/api/v1/teams" {
		t.Errorf("upstream path = %s, want /api/v1/teams", lastReq.URL.Path)
	}
	if lastReq.URL.RawQuery != "page=2" {
		t.Errorf("upstream query = %q, want page=2", lastReq.URL.RawQuery)
	}
	if got := lastReq.Header.Get("Authorization"); got != "Bearer test-token-123" {
		t.Errorf("upstream Authorization = %q, want Bearer test-token-123", got)
	}
}

// TestProjectServiceProxyStripsClientUserID 安全断言:客户端伪造的 X-User-Id
// 在转发时被无条件剥离,上游收到的请求不含客户端注入的身份。
func TestProjectServiceProxyStripsClientUserID(t *testing.T) {
	upstream, getLastReq := startUpstream(t)
	r := newProxyRouter(t, upstream.URL)
	srv := httptest.NewServer(r)
	defer srv.Close()

	req, err := http.NewRequest(http.MethodGet, srv.URL+"/api/v1/teams", nil)
	if err != nil {
		t.Fatal(err)
	}
	req.Header.Set("X-User-Id", "evil-user-id")

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()
	if resp.StatusCode != http.StatusCreated {
		t.Fatalf("status = %d, want %d", resp.StatusCode, http.StatusCreated)
	}

	lastReq := getLastReq()
	if lastReq == nil {
		t.Fatal("upstream did not receive request")
	}
	if got := lastReq.Header.Get("X-User-Id"); got != "" {
		t.Errorf("upstream X-User-Id = %q, want empty (client value must be stripped)", got)
	}
}

// TestProjectServiceProxyInjectsTrustedUserID 安全断言:带有效 JWT 的请求
// 即使客户端携带伪造 X-User-Id:evil,上游收到的也是 gateway 校验后的可信 user_id。
func TestProjectServiceProxyInjectsTrustedUserID(t *testing.T) {
	upstream, getLastReq := startUpstream(t)
	r, tokens := newProxyAuthedRouter(t, upstream.URL)
	srv := httptest.NewServer(r)
	defer srv.Close()

	token, err := tokens.Sign(proxyTestUserID)
	if err != nil {
		t.Fatalf("Sign() error = %v, want nil", err)
	}

	req, err := http.NewRequest(http.MethodGet, srv.URL+"/api/v1/teams", nil)
	if err != nil {
		t.Fatal(err)
	}
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("X-User-Id", "evil-user-id")

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()
	if resp.StatusCode != http.StatusCreated {
		t.Fatalf("status = %d, want %d", resp.StatusCode, http.StatusCreated)
	}

	lastReq := getLastReq()
	if lastReq == nil {
		t.Fatal("upstream did not receive request")
	}
	if got := lastReq.Header.Get("X-User-Id"); got != proxyTestUserID {
		t.Errorf("upstream X-User-Id = %q, want trusted %q", got, proxyTestUserID)
	}
}

// TestProjectServiceProxyRouteCoverage 验证 teams/projects 前缀的精确与子路径路由均被转发,
// 不相关路径(含已收归本地的 /api/v1/users 前缀)不被转发。
func TestProjectServiceProxyRouteCoverage(t *testing.T) {
	upstream, _ := startUpstream(t)
	r := newProxyRouter(t, upstream.URL)
	srv := httptest.NewServer(r)
	defer srv.Close()

	proxied := []string{
		"/api/v1/teams",
		"/api/v1/teams?keyword=abc",
		"/api/v1/teams/abc-123/members",
		"/api/v1/teams/abc-123/projects",
		"/api/v1/projects",
		"/api/v1/projects/abc-123",
		// 用户域子资源:本地实现 /users、/users/me,以下仍由 project-service 提供
		"/api/v1/users/me/teams",
		"/api/v1/users/me/projects",
	}
	for _, p := range proxied {
		resp, err := http.Get(srv.URL + p)
		if err != nil {
			t.Fatalf("GET %s: %v", p, err)
		}
		resp.Body.Close()
		if resp.StatusCode != http.StatusCreated {
			t.Errorf("GET %s: status = %d, want %d (proxied)", p, resp.StatusCode, http.StatusCreated)
		}
	}

	notProxied := []string{
		"/api/v1/users",
		"/api/v1/users/me",
		"/api/v1/auth",
		"/api/v1/auth/auto-register",
		"/api/v1/chats",
		"/api/v1/project",
		"/api/v1/team",
		"/health",
	}
	for _, p := range notProxied {
		resp, err := http.Get(srv.URL + p)
		if err != nil {
			t.Fatalf("GET %s: %v", p, err)
		}
		resp.Body.Close()
		if resp.StatusCode != http.StatusNotFound {
			t.Errorf("GET %s: status = %d, want 404 (not proxied)", p, resp.StatusCode)
		}
	}
}

// TestProjectServiceProxyUpstreamDown 验证上游不可达时返回 502 + JSON 错误体。
func TestProjectServiceProxyUpstreamDown(t *testing.T) {
	// 先占用一个端口再关闭,拿到一个必然连接失败的地址。
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	addr := ln.Addr().String()
	ln.Close()

	r := newProxyRouter(t, "http://"+addr)
	srv := httptest.NewServer(r)
	defer srv.Close()

	resp, err := http.Get(srv.URL + "/api/v1/projects")
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusBadGateway {
		t.Fatalf("status = %d, want 502", resp.StatusCode)
	}
	body, _ := io.ReadAll(resp.Body)
	var parsed map[string]string
	if err := json.Unmarshal(body, &parsed); err != nil {
		t.Fatalf("body is not JSON: %q (%v)", body, err)
	}
	if parsed["error"] == "" {
		t.Fatalf("body missing error field: %q", body)
	}
}

// TestNewProjectServiceProxyAddrValidation 表驱动验证上游地址校验:
// 仅接受 http/https scheme、必须带 host、不允许 path 与 query。
func TestNewProjectServiceProxyAddrValidation(t *testing.T) {
	valid := []string{
		"http://localhost:8081",
		"https://project-service:8081",
		"http://127.0.0.1:8081/", // 尾部斜杠等价于无 path
	}
	for _, addr := range valid {
		if _, err := NewProjectServiceProxy(addr); err != nil {
			t.Errorf("NewProjectServiceProxy(%q) = %v, want nil error", addr, err)
		}
	}

	invalid := []struct {
		addr string
		why  string
	}{
		{"", "empty"},
		{"localhost:8081", "no scheme"},
		{"://bad", "unparseable"},
		{"ftp://localhost:8081", "non-http scheme"},
		{"http://localhost:8081/base/", "has path"},
		{"http://localhost:8081?key=value", "has query"},
	}
	for _, tc := range invalid {
		if _, err := NewProjectServiceProxy(tc.addr); err == nil {
			t.Errorf("NewProjectServiceProxy(%q) = nil error, want error (%s)", tc.addr, tc.why)
		}
	}
}

// TestProjectServiceProxyRejectsNonProxyMethods 验证 CONNECT/TRACE 不被转发:
// httputil.ReverseProxy 不支持 CONNECT 隧道,TRACE 亦无转发意义。
func TestProjectServiceProxyRejectsNonProxyMethods(t *testing.T) {
	upstream, getLastReq := startUpstream(t)
	r := newProxyRouter(t, upstream.URL)

	for _, method := range []string{http.MethodConnect, http.MethodTrace} {
		req := httptest.NewRequest(method, "/api/v1/teams", nil)
		rec := httptest.NewRecorder()
		r.ServeHTTP(rec, req)
		if rec.Code == http.StatusCreated {
			t.Errorf("%s /api/v1/teams: status = %d, want non-proxied (not 201)", method, rec.Code)
		}
	}
	if getLastReq() != nil {
		t.Error("upstream received a request for a non-proxied method")
	}
}

// TestProxyRoutesRequireAuth 回归测试:按 main.go 的真实装配顺序
// (先挂全局 Auth 再 proxy.Register)验证转发路由全部经过 gateway 鉴权,
// 无有效 JWT 的请求返回 401,不触碰上游。
func TestProxyRoutesRequireAuth(t *testing.T) {
	upstream, getLastReq := startUpstream(t)
	r, tokens := newProxyAuthedRouter(t, upstream.URL)
	srv := httptest.NewServer(r)
	defer srv.Close()

	// 无 token:转发路由被 Auth 拦截,返回 401 信封。
	resp, err := http.Get(srv.URL + "/api/v1/teams")
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()
	if resp.StatusCode != http.StatusUnauthorized {
		t.Fatalf("proxy route without token status = %d, want 401", resp.StatusCode)
	}
	if getLastReq() != nil {
		t.Error("upstream received a request without auth")
	}

	// 带有效 token:鉴权通过,正常转发并注入可信 X-User-Id。
	token, err := tokens.Sign(proxyTestUserID)
	if err != nil {
		t.Fatalf("Sign() error = %v, want nil", err)
	}
	req, err := http.NewRequest(http.MethodGet, srv.URL+"/api/v1/projects", nil)
	if err != nil {
		t.Fatal(err)
	}
	req.Header.Set("Authorization", "Bearer "+token)
	resp2, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	resp2.Body.Close()
	if resp2.StatusCode != http.StatusCreated {
		t.Fatalf("proxy route with token status = %d, want %d", resp2.StatusCode, http.StatusCreated)
	}
	lastReq := getLastReq()
	if lastReq == nil {
		t.Fatal("upstream did not receive request")
	}
	if got := lastReq.Header.Get("X-User-Id"); got != proxyTestUserID {
		t.Errorf("upstream X-User-Id = %q, want trusted %q", got, proxyTestUserID)
	}
}
