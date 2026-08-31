package main

import (
	"context"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"ai-design-platform/gateway/internal/auth"
	"ai-design-platform/gateway/internal/client"
	"ai-design-platform/gateway/internal/config"
	"ai-design-platform/gateway/internal/handler"
	"ai-design-platform/gateway/internal/middleware"
	"ai-design-platform/gateway/internal/store"

	"github.com/gin-gonic/gin"
)

func main() {
	// 日志
	slog.SetDefault(slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{
		Level: slog.LevelInfo,
	})))

	// 配置
	cfg, err := config.Load()
	if err != nil {
		slog.Error("Failed to load config", "error", err)
		os.Exit(1)
	}

	// 数据库连接池(users 表访问)
	db, err := store.NewPool(cfg.DatabaseURL)
	if err != nil {
		slog.Error("Failed to create database pool", "error", err)
		os.Exit(1)
	}
	defer db.Close()

	// 启动自检:ping 失败即退出
	pingCtx, pingCancel := context.WithTimeout(context.Background(), 10*time.Second)
	err = store.Check(pingCtx, db)
	pingCancel()
	if err != nil {
		slog.Error("Failed to connect to database", "error", err)
		os.Exit(1)
	}

	// users 表建表:DDL 唯一归属 gateway(全局服务),project-service 迁移仅引用。
	// 因此 gateway 必须早于 project-service 启动(compose 已约束 depends_on)。
	ensureCtx, ensureCancel := context.WithTimeout(context.Background(), 10*time.Second)
	err = store.EnsureUsersTable(ensureCtx, db)
	ensureCancel()
	if err != nil {
		slog.Error("Failed to ensure users table", "error", err)
		os.Exit(1)
	}

	// AI 服务的 gRPC 客户端
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	aiClient, err := client.NewAIClient(ctx, cfg.AIServiceAddr)
	if err != nil {
		slog.Error("Failed to connect to AI service", "error", err)
		os.Exit(1)
	}
	defer aiClient.Close()

	// 处理器
	healthH := handler.NewHealthHandler()
	chatH := handler.NewChatHandler(aiClient)
	convH := handler.NewConversationHandler(aiClient)
	graphHandler := handler.NewGraphSSEHandler(aiClient)
	e2eHandler := handler.NewE2EHandler(graphHandler, aiClient)
	prdHandler := handler.NewPRDHandler(aiClient)
	compileHandler := handler.NewCompileHandler(cfg.NodeCompilerAddr)
	tokens := auth.NewManager(cfg.JWTSecret)
	userH := handler.NewUserHandler(store.NewUsers(db), tokens)

	// Gin 路由器
	gin.SetMode(gin.ReleaseMode)
	r := gin.New()
	r.Use(gin.Recovery())
	r.Use(middleware.Logging())

	// 公开路由:健康检查与自动注册(POST /users 无需登录)。
	r.GET("/health", healthH.Health)
	r.GET("/ready", healthH.Ready)
	publicAPI := r.Group("/api/v1")
	publicAPI.POST("/users", userH.AutoRegister)

	// 全局鉴权中间件:此后注册的路由全部需要有效 JWT。
	r.Use(middleware.Auth(tokens))

	// 需鉴权路由:当前用户信息 + 现有 AI 链路。
	api := r.Group("/api/v1")
	api.GET("/users/me", userH.Me)

	// 原始聊天
	api.POST("/prd/stream", prdHandler.StreamPRD)

	api.POST("/chat/stream", chatH.StreamChat)
	api.POST("/chat/cancel/:id", chatH.CancelChat)

	// 对话管理
	api.POST("/conversations", convH.CreateConversation)
	api.GET("/conversations", convH.ListConversations)
	api.GET("/conversations/:id", convH.GetConversation)
	api.POST("/conversations/:id/messages", convH.SendMessage)
	api.DELETE("/conversations/:id", convH.DeleteConversation)

	// LangGraph 流式生成
	api.POST("/generation/stream", graphHandler.StreamGeneration)
	api.POST("/e2e/result", e2eHandler.SubmitE2EResult)
	api.POST("/generation/confirm", e2eHandler.ConfirmStage)
	api.POST("/generation/compile_feedback", e2eHandler.SubmitCompileFeedback)
	api.POST("/generation/compile", compileHandler.SubmitCompile)
	api.POST("/generation/feedback", graphHandler.SubmitFeedback)

	// project-service 反向代理路由(teams/projects)。
	// 在 auth 中间件挂载之后注册:gin 的路由只经过注册时已挂载的全局中间件,
	// 因此转发请求先经 gateway 鉴权,再注入可信 X-User-Id 传给 project-service。
	projectProxy, err := handler.NewProjectServiceProxy(cfg.ProjectServiceAddr)
	if err != nil {
		slog.Error("Failed to create project service proxy", "error", err)
		os.Exit(1)
	}
	projectProxy.Register(r)

	// HTTP 服务器
	srv := &http.Server{
		Addr:         ":" + cfg.ServerPort,
		Handler:      r,
		ReadTimeout:  30 * time.Second, // 读取请求体
		WriteTimeout: 10 * time.Minute, // SSE 长连接，匹配 AI 服务 600s 超时
		IdleTimeout:  5 * time.Minute,  // Keep-alive 空闲超时
	}

	// 优雅关闭
	go func() {
		quit := make(chan os.Signal, 1)
		signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
		<-quit
		slog.Info("Shutting down server...")

		shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer shutdownCancel()

		if err := srv.Shutdown(shutdownCtx); err != nil {
			slog.Error("Server forced to shutdown", "error", err)
		}
	}()

	slog.Info("Gateway server starting", "port", cfg.ServerPort)
	if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		slog.Error("Server failed", "error", err)
		os.Exit(1)
	}
	slog.Info("Server stopped")
}
