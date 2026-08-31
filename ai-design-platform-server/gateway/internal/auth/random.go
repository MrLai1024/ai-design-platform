package auth

import (
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"math/big"
)

// accountRandomBytes 是账号随机串的字节数(hex 编码后为 12 个字符)。
const accountRandomBytes = 6

const (
	// passwordLength 密码长度:16 位,满足"12+ 位"的设计要求。
	passwordLength = 16
	lowerChars     = "abcdefghijklmnopqrstuvwxyz"
	upperChars     = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
	digitChars     = "0123456789"
	passwordChars  = lowerChars + upperChars + digitChars
)

// RandomAccount 生成 `user_` 前缀 + 12 位十六进制随机串的账号。
// 唯一性由 users.account 唯一约束 + 注册重试兜底。
func RandomAccount() (string, error) {
	buf := make([]byte, accountRandomBytes)
	if _, err := rand.Read(buf); err != nil {
		return "", fmt.Errorf("read random bytes: %w", err)
	}
	return "user_" + hex.EncodeToString(buf), nil
}

// RandomPassword 生成 16 位随机密码,保证至少包含一个小写字母、一个大写字母与一个数字。
func RandomPassword() (string, error) {
	b := make([]byte, passwordLength)
	for i := range b {
		ch, err := randomChar(passwordChars)
		if err != nil {
			return "", fmt.Errorf("generate password: %w", err)
		}
		b[i] = ch
	}
	// 在三个随机互异位置强制注入三类字符,兜底保证复杂度。
	used := make(map[int]bool, 3)
	for _, charset := range []string{lowerChars, upperChars, digitChars} {
		if err := injectAtRandomPosition(b, charset, used); err != nil {
			return "", err
		}
	}
	return string(b), nil
}

// injectAtRandomPosition 在 b 的随机一个未注入过的位置放入 charset 中的随机字符。
func injectAtRandomPosition(b []byte, charset string, used map[int]bool) error {
	for {
		n, err := rand.Int(rand.Reader, big.NewInt(int64(len(b))))
		if err != nil {
			return fmt.Errorf("pick password position: %w", err)
		}
		pos := int(n.Int64())
		if used[pos] {
			continue
		}
		used[pos] = true
		ch, err := randomChar(charset)
		if err != nil {
			return fmt.Errorf("generate password: %w", err)
		}
		b[pos] = ch
		return nil
	}
}

// randomChar 从字符集中均匀随机取一个字符。
func randomChar(charset string) (byte, error) {
	n, err := rand.Int(rand.Reader, big.NewInt(int64(len(charset))))
	if err != nil {
		return 0, fmt.Errorf("read random int: %w", err)
	}
	return charset[n.Int64()], nil
}
