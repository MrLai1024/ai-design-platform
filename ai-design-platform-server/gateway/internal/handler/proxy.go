package handler

import (
	"encoding/json"
	"fmt"
	"log/slog"
	"net"
	"net/http"
	"net/http/httputil"
	"net/url"
	"time"

	"github.com/gin-gonic/gin"
)

// projectServiceProxyPrefixes 是需要转发到 project-service 的路由前缀。
// 鉴权由 project-service 自行完成,gateway 对这些路由只做纯反向代理。
var projectServiceProxyPrefixes = []string{
	"/api/v1/auth",
	"/api/v1/teams",
	"/api/v1/projects",
}

// ProjectServiceProxy 将用户/团队/项目域接口反向代理到 project-service。
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
// 注意:必须在全局 Auth 中间件挂载之前调用——gin 的路由只会经过注册时已挂载的
// 全局中间件,先注册即可保证转发请求不经过 gateway 的 auth 中间件(5.2)。
func (p *ProjectServiceProxy) Register(r *gin.Engine) {
	for _, prefix := range projectServiceProxyPrefixes {
		for _, method := range proxyMethods {
			r.Handle(method, prefix, p.ServeHTTP)
			r.Handle(method, prefix+"/*proxyPath", p.ServeHTTP)
		}
	}
}

// ServeHTTP 将请求原样转发到 project-service:
// 保留请求路径与 query(如 /api/v1/teams/search?keyword=x)、转发 Authorization 头、
// 透传响应体与状态码。这些接口均为普通 JSON 接口,无需 SSE 特殊处理。
func (p *ProjectServiceProxy) ServeHTTP(c *gin.Context) {
	p.proxy.ServeHTTP(c.Writer, c.Request)
}
