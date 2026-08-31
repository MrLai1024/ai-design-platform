package config

import "testing"

func TestLoadDefaults(t *testing.T) {
	// 清空环境变量,验证默认值。
	t.Setenv("PROJECT_SERVICE_PORT", "")
	t.Setenv("DATABASE_URL", "")

	cfg, err := Load()
	if err != nil {
		t.Fatalf("Load() error = %v, want nil", err)
	}
	if cfg.ServerPort != "8081" {
		t.Errorf("ServerPort = %q, want %q", cfg.ServerPort, "8081")
	}
	if want := "postgres://aiplatform:aiplatform@localhost:5432/aiplatform?sslmode=disable"; cfg.DatabaseURL != want {
		t.Errorf("DatabaseURL = %q, want %q", cfg.DatabaseURL, want)
	}
}

func TestLoadFromEnv(t *testing.T) {
	t.Setenv("PROJECT_SERVICE_PORT", "9090")
	t.Setenv("DATABASE_URL", "postgres://user:pass@db:5432/mydb?sslmode=disable")

	cfg, err := Load()
	if err != nil {
		t.Fatalf("Load() error = %v, want nil", err)
	}
	if cfg.ServerPort != "9090" {
		t.Errorf("ServerPort = %q, want %q", cfg.ServerPort, "9090")
	}
	if cfg.DatabaseURL != "postgres://user:pass@db:5432/mydb?sslmode=disable" {
		t.Errorf("DatabaseURL = %q, want overridden value", cfg.DatabaseURL)
	}
}

func TestLoadRequiresDatabaseURL(t *testing.T) {
	t.Setenv("DATABASE_URL", "   ")

	if _, err := Load(); err == nil {
		t.Fatal("Load() error = nil, want error for blank DATABASE_URL")
	}
}
