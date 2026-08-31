package auth

import (
	"errors"
	"strings"
	"testing"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

// baseTime 是所有测试的基准时间。
var baseTime = time.Date(2026, 8, 25, 12, 0, 0, 0, time.UTC)

// newFixedManager 创建时钟固定为 baseTime 的 Manager。
func newFixedManager(secret string) *Manager {
	return newManagerWithClock(secret, func() time.Time { return baseTime })
}

func TestSignVerifyRoundtrip(t *testing.T) {
	m := newFixedManager("test-secret")

	token, err := m.Sign("user-123")
	if err != nil {
		t.Fatalf("Sign() error = %v, want nil", err)
	}
	if got := len(strings.Split(token, ".")); got != 3 {
		t.Errorf("token %q has %d segments, want 3", token, got)
	}

	userID, err := m.Verify(token)
	if err != nil {
		t.Fatalf("Verify() error = %v, want nil", err)
	}
	if userID != "user-123" {
		t.Errorf("Verify() userID = %q, want %q", userID, "user-123")
	}
}

func TestVerifyExpiredToken(t *testing.T) {
	sign := newFixedManager("test-secret")
	token, err := sign.Sign("user-123")
	if err != nil {
		t.Fatalf("Sign() error = %v, want nil", err)
	}

	// 有效期内的最后时刻:签发后 7 天减 1 小时,应仍然有效。
	beforeTTL := newManagerWithClock("test-secret", func() time.Time { return baseTime.Add(TokenTTL - time.Hour) })
	if _, err := beforeTTL.Verify(token); err != nil {
		t.Errorf("Verify() before expiry = %v, want nil", err)
	}

	// 超过 7 天:应判定过期。
	expired := newManagerWithClock("test-secret", func() time.Time { return baseTime.Add(TokenTTL + time.Hour) })
	if _, err := expired.Verify(token); !errors.Is(err, jwt.ErrTokenExpired) {
		t.Errorf("Verify() after expiry error = %v, want jwt.ErrTokenExpired", err)
	}
}

func TestVerifyWrongSecret(t *testing.T) {
	token, err := newFixedManager("secret-a").Sign("user-123")
	if err != nil {
		t.Fatalf("Sign() error = %v, want nil", err)
	}

	_, err = newFixedManager("secret-b").Verify(token)
	if !errors.Is(err, jwt.ErrTokenSignatureInvalid) {
		t.Errorf("Verify() with wrong secret error = %v, want jwt.ErrTokenSignatureInvalid", err)
	}
}

func TestVerifyTamperedSignature(t *testing.T) {
	m := newFixedManager("test-secret")
	token, err := m.Sign("user-123")
	if err != nil {
		t.Fatalf("Sign() error = %v, want nil", err)
	}

	// 篡改签名段最后一个字符。
	parts := strings.Split(token, ".")
	sig := parts[2]
	replaced := "A"
	if sig[len(sig)-1] == 'A' {
		replaced = "B"
	}
	parts[2] = sig[:len(sig)-1] + replaced

	if _, err := m.Verify(strings.Join(parts, ".")); err == nil {
		t.Error("Verify() error = nil, want signature error")
	}
}

func TestVerifyMalformedTokens(t *testing.T) {
	m := newFixedManager("test-secret")
	for _, bad := range []string{"", "abc", "a.b", "a.b.c", "not.a.jwt"} {
		if _, err := m.Verify(bad); err == nil {
			t.Errorf("Verify(%q) error = nil, want parse error", bad)
		}
	}
}

func TestVerifyMissingExp(t *testing.T) {
	m := newFixedManager("test-secret")

	// 用同一密钥签发一个不带 exp 的 token,校验必须拒绝。
	raw := jwt.NewWithClaims(jwt.SigningMethodHS256, jwt.MapClaims{"user_id": "user-123"})
	token, err := raw.SignedString(m.secret)
	if err != nil {
		t.Fatalf("SignedString() error = %v, want nil", err)
	}

	if _, err := m.Verify(token); err == nil {
		t.Error("Verify() error = nil, want missing-exp error")
	}
}

func TestVerifyMissingUserID(t *testing.T) {
	m := newFixedManager("test-secret")

	// 用同一密钥签发一个带 exp 但无 user_id 的 token,校验必须拒绝。
	raw := jwt.NewWithClaims(jwt.SigningMethodHS256, jwt.RegisteredClaims{
		ExpiresAt: jwt.NewNumericDate(baseTime.Add(time.Hour)),
	})
	token, err := raw.SignedString(m.secret)
	if err != nil {
		t.Fatalf("SignedString() error = %v, want nil", err)
	}

	if _, err := m.Verify(token); err == nil {
		t.Error("Verify() error = nil, want missing-user_id error")
	}
}
