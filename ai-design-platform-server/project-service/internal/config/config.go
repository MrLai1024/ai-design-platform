package config

import (
	"fmt"
	"os"
	"strings"
)

// Config 保存 project-service 全部配置。
type Config struct {
	ServerPort  string
	DatabaseURL string
	JWTSecret   string
}

// Load 从环境变量读取配置,并提供默认值。
func Load() (*Config, error) {
	cfg := &Config{
		ServerPort:  getEnv("PROJECT_SERVICE_PORT", "8081"),
		DatabaseURL: getEnv("DATABASE_URL", "postgres://aiplatform:aiplatform@localhost:5432/aiplatform?sslmode=disable"),
		JWTSecret:   getEnv("JWT_SECRET", "dev-secret"),
	}

	if strings.TrimSpace(cfg.DatabaseURL) == "" {
		return nil, fmt.Errorf("DATABASE_URL is required")
	}

	return cfg, nil
}

func getEnv(key, defaultVal string) string {
	if val := os.Getenv(key); val != "" {
		return val
	}
	return defaultVal
}
