package handler

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"net"
	"net/http"
	"net/http/httputil"
	"net/url"
	"time"

	"ai-design-platform/gateway/internal/middleware"

	"github.com/gin-gonic/gin"
)

// projectServiceProxyPrefixes 是需要转发到 project-service 的路由前缀。
// 用户域(注册/用户信息)已由 gateway 本地实现,不再反代;teams/projects 仍由 project-service 提供。
var projectServiceProxyPrefixes = []string{
	"/api/v1/teams",
	"/api/v1/projects",
	// 用户域:gateway 本地实现 /users、/users/me;子资源(我的团队/项目)仍由 project-service 提供
	"/api/v1/users/me/teams",
	"/api/v1/users/me/projects",
}

// trustedUserIDKey 是转发请求 context 中可信 user_id 的键,
// 由 ServeHTTP 从 gin context 写入,Director 读取后注入上游请求头。
type trustedUserIDKey struct{}

// ProjectServiceProxy 将团队/项目域接口反向代理到 project-service。
type ProjectServiceProxy struct {
	proxy *httputil.ReverseProxy
}

// NewProjectServiceProxy 创建指向 upstreamAddr(如 http://localhost:8081)的反向代理。
// upstreamAddr 要求带 scheme 与 host,不允许携带 path(上游路由与 gateway 完全一致)。
func NewProjectServiceProxy(upstreamAddr string) (*ProjectServiceProxy, error) {
	target, err := url.Parse(upstreamAddr)
	if err != nil {
		return nil, fmt.Errorf("invalid PROJECT_SERVICE_ADDR %q: %w", upstreamAddr, err)
	}
	if target.Scheme != "http" && target.Scheme != "https" {
		return nil, fmt.Errorf("invalid PROJECT_SERVICE_ADDR %q: scheme must be http or https", upstreamAddr)
	}
	if target.Host == "" {
		return nil, fmt.Errorf("invalid PROJECT_SERVICE_ADDR %q: must include a host", upstreamAddr)
	}
	if target.Path != "" && target.Path != "/" {
		return nil, fmt.Errorf("invalid PROJECT_SERVICE_ADDR %q: must not include a path", upstreamAddr)
	}
	if target.RawQuery != "" {
		return nil, fmt.Errorf("invalid PROJECT_SERVICE_ADDR %q: must not include a query string", upstreamAddr)
	}

	transport := &http.Transport{
		DialContext:           (&net.Dialer{Timeout: 10 * time.Second, KeepAlive: 30 * time.Second}).DialContext,
		MaxIdleConns:          100,
		IdleConnTimeout:       90 * time.Second,
		TLSHandshakeTimeout:   10 * time.Second,
		ResponseHeaderTimeout: 30 * time.Second,
		ExpectContinueTimeout: 1 * time.Second,
	}

	proxy := httputil.NewSingleHostReverseProxy(target)
	proxy.Transport = transport
	// 身份注入:剥离客户端伪造的 X-User-Id,注入 gateway 校验后的可信 user_id。
	// 安全要点:project-service 信任此 header,因此必须无条件先 Del 再 Set,
	// 客户端无法伪造身份;userID 来自 Auth 中间件解析的 JWT claims。
	defaultDirector := proxy.Director
	proxy.Director = func(req *http.Request) {
		defaultDirector(req)
		req.Header.Del("X-User-Id")
		if userID, ok := req.Context().Value(trustedUserIDKey{}).(string); ok && userID != "" {
			req.Header.Set("X-User-Id", userID)
		}
	}
	// 上游不可达时返回 502 + 统一错误体,与 project-service 的错误格式保持一致。
	proxy.ErrorHandler = func(w http.ResponseWriter, r *http.Request, err error) {
		slog.Error("project service proxy error", "error", err, "path", r.URL.Path)
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusBadGateway)
		_ = json.NewEncoder(w).Encode(map[string]string{
			"error": "project service unavailable",
		})
	}

	return &ProjectServiceProxy{proxy: proxy}, nil
}

// proxyMethods 是允许转发的 HTTP 方法。
// httputil.ReverseProxy 不支持 CONNECT 隧道,TRACE 也无需转发,故排除在外。
var proxyMethods = []string{
	http.MethodGet, http.MethodHead, http.MethodPost,
	http.MethodPut, http.MethodPatch, http.MethodDelete, http.MethodOptions,
}

// Register 在 r 上注册转发路由(前缀精确匹配 + 子路径通配)。
// 注意:必须在全局 Auth 中间件挂载之后调用——gin 的路由只会经过注册时已挂载的
// 全局中间件,先挂 auth 再注册即可保证转发请求先经过 gateway 鉴权。
func (p *ProjectServiceProxy) Register(r *gin.Engine) {
	for _, prefix := range projectServiceProxyPrefixes {
		for _, method := range proxyMethods {
			r.Handle(method, prefix, p.ServeHTTP)
			r.Handle(method, prefix+"/*proxyPath", p.ServeHTTP)
		}
	}
}

// ServeHTTP 将请求转发到 project-service:
// 保留请求路径与 query(如 /api/v1/teams?keyword=x)、转发 Authorization 头、
// 透传响应体与状态码。这些接口均为普通 JSON 接口,无需 SSE 特殊处理。
// 转发前将 Auth 中间件注入的可信 user_id 写入 request context,
// 由 Director 读取后以 X-User-Id header 形式传给上游。
func (p *ProjectServiceProxy) ServeHTTP(c *gin.Context) {
	if userID, ok := middleware.GetUserID(c); ok {
		c.Request = c.Request.WithContext(context.WithValue(c.Request.Context(), trustedUserIDKey{}, userID))
	}
	p.proxy.ServeHTTP(c.Writer, c.Request)
}
