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
	// Logger
	slog.SetDefault(slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{
		Level: slog.LevelInfo,
	})))

	// Config
	cfg, err := config.Load()
	if err != nil {
		slog.Error("Failed to load config", "error", err)
		os.Exit(1)
	}

	// gRPC client to AI service
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	aiClient, err := client.NewAIClient(ctx, cfg.AIServiceAddr)
	if err != nil {
		slog.Error("Failed to connect to AI service", "error", err)
		os.Exit(1)
	}
	defer aiClient.Close()

	// Handlers
	healthH := handler.NewHealthHandler()
	chatH := handler.NewChatHandler(aiClient)

	// Gin router
	gin.SetMode(gin.ReleaseMode)
	r := gin.New()
	r.Use(gin.Recovery())
	r.Use(middleware.Logging())
	r.Use(middleware.Auth())

	// Routes
	r.GET("/health", healthH.Health)
	r.GET("/ready", healthH.Ready)

	api := r.Group("/api/v1")
	{
		api.POST("/chat/stream", chatH.StreamChat)
		api.POST("/chat/cancel/:id", chatH.CancelChat)
	}

	// HTTP server
	srv := &http.Server{
		Addr:         ":" + cfg.ServerPort,
		Handler:      r,
		ReadTimeout:  10 * time.Second,
		WriteTimeout: 5 * time.Minute, // SSE connections are long-lived
		IdleTimeout:  2 * time.Minute,
	}

	// Graceful shutdown
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
