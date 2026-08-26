package main

import (
	"context"
	"database/sql"
	"errors"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"ai-design-platform/project-service/internal/auth"
	"ai-design-platform/project-service/internal/config"
	"ai-design-platform/project-service/internal/handler"
	"ai-design-platform/project-service/internal/middleware"
	"ai-design-platform/project-service/internal/store"
	"ai-design-platform/project-service/migrations"

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

	// 数据库连接池
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

	// 启动时幂等迁移
	migrateCtx, migrateCancel := context.WithTimeout(context.Background(), 30*time.Second)
	err = store.NewMigrator(db, migrations.FS).Run(migrateCtx)
	migrateCancel()
	if err != nil {
		slog.Error("Failed to run migrations", "error", err)
		os.Exit(1)
	}

	// Gin 路由器
	r := newRouter(cfg, db)

	// HTTP 服务器
	srv := &http.Server{
		Addr:         ":" + cfg.ServerPort,
		Handler:      r,
		ReadTimeout:  30 * time.Second,
		WriteTimeout: 30 * time.Second,
		IdleTimeout:  5 * time.Minute,
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

	slog.Info("Project service starting", "port", cfg.ServerPort)
	if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
		slog.Error("Server failed", "error", err)
		os.Exit(1)
	}
	slog.Info("Server stopped")
}

// newRouter 装配全部路由。
// health 与 auto-register 公开;其余用户域接口统一挂认证中间件。
func newRouter(cfg *config.Config, db *sql.DB) *gin.Engine {
	gin.SetMode(gin.ReleaseMode)
	r := gin.New()
	r.Use(gin.Recovery())

	healthH := handler.NewHealthHandler()
	r.GET("/health", healthH.Health)

	users := store.NewUsers(db)
	tokens := auth.NewManager(cfg.JWTSecret)

	api := r.Group("/api/v1")

	// auth 路由组:auto-register 公开;/me 需认证。
	authH := handler.NewAuthHandler(users, tokens)
	authGroup := api.Group("/auth")
	authGroup.POST("/auto-register", authH.AutoRegister)
	authGroup.GET("/me", middleware.Auth(tokens), authH.Me)

	// teams 路由组:/:id/projects 为团队项目列表,由 ProjectHandler 提供。
	teamH := handler.NewTeamHandler(store.NewTeams(db))
	teams := api.Group("/teams", middleware.Auth(tokens))
	teams.GET("", teamH.List)
	teams.POST("", teamH.Create)
	teams.GET("/search", teamH.Search)
	teams.POST("/:id/join", teamH.Join)

	projectH := handler.NewProjectHandler(store.NewProjects(db))
	teams.GET("/:id/projects", projectH.TeamProjects)

	projects := api.Group("/projects", middleware.Auth(tokens))
	projects.GET("", projectH.List)
	projects.POST("", projectH.Create)
	projects.GET("/:id", projectH.Detail)

	return r
}
