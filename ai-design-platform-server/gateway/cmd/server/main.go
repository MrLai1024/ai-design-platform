package main

import (
	"context"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"ai-design-platform/gateway/internal/client"
	"ai-design-platform/gateway/internal/config"
	"ai-design-platform/gateway/internal/handler"
	"ai-design-platform/gateway/internal/middleware"

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
	intentHandler := handler.NewIntentHandler(aiClient)
	brainstormHandler := handler.NewBrainstormHandler(aiClient)

	// Gin 路由器
	gin.SetMode(gin.ReleaseMode)
	r := gin.New()
	r.Use(gin.Recovery())
	r.Use(middleware.Logging())
	r.Use(middleware.Auth())

	// 路由
	r.GET("/health", healthH.Health)
	r.GET("/ready", healthH.Ready)

	api := r.Group("/api/v1")
	{
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
		api.POST("/generation/runtime-feedback", e2eHandler.SubmitRuntimeFeedback)
		api.POST("/generation/feedback", graphHandler.SubmitFeedback)
		api.POST("/generation/intent", intentHandler.ClassifyIntent)
		api.POST("/generation/brainstorm", brainstormHandler.Turn)
	}

	// HTTP 服务器
	srv := &http.Server{
		Addr:         ":" + cfg.ServerPort,
		Handler:      r,
		ReadTimeout:  30 * time.Second,    // 读取请求体
		WriteTimeout: 10 * time.Minute,    // SSE 长连接，匹配 AI 服务 600s 超时
		IdleTimeout:  5 * time.Minute,     // Keep-alive 空闲超时
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
