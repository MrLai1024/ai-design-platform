package config

import (
	"fmt"
	"os"
	"strings"
)

// Config 保存所有网关配置。
type Config struct {
	ServerPort    string
	AIServiceAddr string
	DatabaseURL   string
	RedisAddr     string
	LogLevel      string
}

// Load 从环境变量读取配置，并提供默认值。
func Load() (*Config, error) {
	cfg := &Config{
		ServerPort:    getEnv("SERVER_PORT", "8080"),
		AIServiceAddr: getEnv("AI_SERVICE_ADDR", "localhost:50051"),
		DatabaseURL:   getEnv("DATABASE_URL", "postgres://aiplatform:aiplatform@localhost:5432/aiplatform?sslmode=disable"),
		RedisAddr:     getEnv("REDIS_ADDR", "localhost:6379"),
		LogLevel:      getEnv("LOG_LEVEL", "info"),
	}

	if strings.TrimSpace(cfg.AIServiceAddr) == "" {
		return nil, fmt.Errorf("AI_SERVICE_ADDR is required")
	}

	return cfg, nil
}

func getEnv(key, defaultVal string) string {
	if val := os.Getenv(key); val != "" {
		return val
	}
	return defaultVal
}
