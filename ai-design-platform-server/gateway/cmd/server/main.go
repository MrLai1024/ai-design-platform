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
		api.POST("/chat/stream", chatH.StreamChat)
		api.POST("/chat/cancel/:id", chatH.CancelChat)

		// 对话管理
		api.POST("/conversations", convH.CreateConversation)
		api.GET("/conversations", convH.ListConversations)
		api.GET("/conversations/:id", convH.GetConversation)
		api.POST("/conversations/:id/messages", convH.SendMessage)
		api.DELETE("/conversations/:id", convH.DeleteConversation)
	}

	// HTTP 服务器
	srv := &http.Server{
		Addr:         ":" + cfg.ServerPort,
		Handler:      r,
		ReadTimeout:  10 * time.Second,
		WriteTimeout: 5 * time.Minute, // SSE 连接是长连接
		IdleTimeout:  2 * time.Minute,
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
