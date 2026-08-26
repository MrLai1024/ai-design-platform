// Package auth 提供 JWT 签发/校验(HS256,与 gateway 共享 JWT_SECRET)与账号密码随机生成。
package auth

import (
	"errors"
	"fmt"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

// TokenTTL 是签发 token 的有效期(7 天)。
const TokenTTL = 7 * 24 * time.Hour

// Claims 是 project-service 签发的 JWT claims,user_id 标识用户。
type Claims struct {
	UserID string `json:"user_id"`
	jwt.RegisteredClaims
}

// Manager 负责 JWT(HS256)的签发与校验。
type Manager struct {
	secret []byte
	now    func() time.Time
}

// NewManager 创建使用真实时钟的 Manager。
func NewManager(secret string) *Manager {
	return newManagerWithClock(secret, time.Now)
}

// newManagerWithClock 创建使用指定时钟的 Manager(测试注入固定时钟)。
func newManagerWithClock(secret string, now func() time.Time) *Manager {
	return &Manager{secret: []byte(secret), now: now}
}

// Sign 为指定用户签发 token,claims 含 user_id 与签发/过期时间。
func (m *Manager) Sign(userID string) (string, error) {
	now := m.now()
	claims := Claims{
		UserID: userID,
		RegisteredClaims: jwt.RegisteredClaims{
			IssuedAt:  jwt.NewNumericDate(now),
			ExpiresAt: jwt.NewNumericDate(now.Add(TokenTTL)),
		},
	}
	token, err := jwt.NewWithClaims(jwt.SigningMethodHS256, claims).SignedString(m.secret)
	if err != nil {
		return "", fmt.Errorf("sign token: %w", err)
	}
	return token, nil
}

// Verify 校验 token 的签名与有效期,返回 claims 中的 user_id。
// 签名不符、已过期、格式非法或缺少必要 claims 时返回错误。
func (m *Manager) Verify(tokenString string) (string, error) {
	var claims Claims
	// 过期校验使用 Manager 自身时钟(默认 time.Now,测试可注入固定时钟)。
	token, err := jwt.ParseWithClaims(tokenString, &claims, func(t *jwt.Token) (any, error) {
		if _, ok := t.Method.(*jwt.SigningMethodHMAC); !ok {
			return nil, fmt.Errorf("unexpected signing method: %v", t.Header["alg"])
		}
		return m.secret, nil
	}, jwt.WithTimeFunc(m.now))
	if err != nil {
		return "", fmt.Errorf("parse token: %w", err)
	}
	if !token.Valid {
		return "", errors.New("invalid token")
	}
	if claims.ExpiresAt == nil {
		return "", errors.New("token missing exp")
	}
	if claims.UserID == "" {
		return "", errors.New("token missing user_id claim")
	}
	return claims.UserID, nil
}
