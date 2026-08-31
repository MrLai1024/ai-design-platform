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
// 用户域(注册/当前用户)已迁至 gateway;本服务只保留 teams/projects 业务路由,
// 全部挂 X-User-Id 信任中间件(gateway 校验 JWT 后注入该 header)。
func newRouter(cfg *config.Config, db *sql.DB) *gin.Engine {
	gin.SetMode(gin.ReleaseMode)
	r := gin.New()
	r.Use(gin.Recovery())

	healthH := handler.NewHealthHandler()
	r.GET("/health", healthH.Health)

	teamH := handler.NewTeamHandler(store.NewTeams(db))
	projectH := handler.NewProjectHandler(store.NewProjects(db))

	api := r.Group("/api/v1")

	// 用户域业务列表路由:/users/me/teams(我的团队)与 /users/me/projects(我的项目)。
	users := api.Group("/users", middleware.Auth())
	users.GET("/me/teams", teamH.List)
	users.GET("/me/projects", projectH.List)

	// teams 路由组:GET "" 为可加入团队列表(搜索,keyword 可选);/:id/projects 由 ProjectHandler 提供。
	teams := api.Group("/teams", middleware.Auth())
	teams.GET("", teamH.Search)
	teams.POST("", teamH.Create)
	teams.POST("/:id/members", teamH.Join)
	teams.GET("/:id/projects", projectH.TeamProjects)

	projects := api.Group("/projects", middleware.Auth())
	projects.POST("", projectH.Create)
	projects.GET("/:id", projectH.Detail)

	return r
}
