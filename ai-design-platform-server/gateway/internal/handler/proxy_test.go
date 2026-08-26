package handler

import (
	"encoding/json"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
)

// newProxyRouter 装配一个只挂代理路由的 gin 引擎(与 main.go 的注册逻辑一致,
// 代理路由在 Auth 之前注册)。
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

	req, err := http.NewRequest(http.MethodPost, srv.URL+"/api/v1/teams/search?keyword=foo&page=2", strings.NewReader(`{"name":"x"}`))
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
	if lastReq.URL.Path != "/api/v1/teams/search" {
		t.Errorf("upstream path = %s, want /api/v1/teams/search", lastReq.URL.Path)
	}
	if lastReq.URL.RawQuery != "keyword=foo&page=2" {
		t.Errorf("upstream query = %q, want keyword=foo&page=2", lastReq.URL.RawQuery)
	}
	if got := lastReq.Header.Get("Authorization"); got != "Bearer test-token-123" {
		t.Errorf("upstream Authorization = %q, want Bearer test-token-123", got)
	}
}

// TestProjectServiceProxyRouteCoverage 验证三条前缀的精确与子路径路由均被转发,
// 不相关路径不被转发。
func TestProjectServiceProxyRouteCoverage(t *testing.T) {
	upstream, _ := startUpstream(t)
	r := newProxyRouter(t, upstream.URL)
	srv := httptest.NewServer(r)
	defer srv.Close()

	proxied := []string{
		"/api/v1/auth",
		"/api/v1/auth/auto-register",
		"/api/v1/teams",
		"/api/v1/teams/search?keyword=abc",
		"/api/v1/teams/abc-123/join",
		"/api/v1/teams/abc-123/projects",
		"/api/v1/projects",
		"/api/v1/projects/abc-123",
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

// TestProxyRoutesBypassAuthMiddleware 回归测试:按 main.go 的真实装配顺序
// (proxy.Register 在 r.Use(Auth) 之前)验证转发路由不经过 auth 中间件。
// 用"严格版"中间件替代桩 Auth(桩总是放行),防止未来装配顺序被移动后静默破坏。
func TestProxyRoutesBypassAuthMiddleware(t *testing.T) {
	upstream, getLastReq := startUpstream(t)
	proxy, err := NewProjectServiceProxy(upstream.URL)
	if err != nil {
		t.Fatal(err)
	}

	r := gin.New()
	// 与 main.go 一致:代理路由先注册……
	proxy.Register(r)
	// ……之后才挂 auth;严格版:一律 401。
	r.Use(func(c *gin.Context) {
		c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "unauthorized"})
	})
	// 对照路由:注册在 auth 之后,应被 auth 拦截。
	r.GET("/api/v1/ai-check", func(c *gin.Context) { c.Status(http.StatusOK) })

	srv := httptest.NewServer(r)
	defer srv.Close()

	// 代理路由不受 auth 影响,正常转发。
	resp, err := http.Get(srv.URL + "/api/v1/teams")
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()
	if resp.StatusCode != http.StatusCreated {
		t.Fatalf("proxy route status = %d, want %d (must bypass auth)", resp.StatusCode, http.StatusCreated)
	}
	if getLastReq() == nil {
		t.Fatal("upstream did not receive request")
	}

	// 对照:auth 之后注册的路由被拦截,证明中间件生效、而非测试未挂上。
	resp2, err := http.Get(srv.URL + "/api/v1/ai-check")
	if err != nil {
		t.Fatal(err)
	}
	resp2.Body.Close()
	if resp2.StatusCode != http.StatusUnauthorized {
		t.Fatalf("post-auth route status = %d, want 401 (control)", resp2.StatusCode)
	}
}
