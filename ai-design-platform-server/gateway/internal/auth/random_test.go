package auth

import (
	"regexp"
	"strings"
	"testing"
)

func TestRandomAccountFormat(t *testing.T) {
	pattern := regexp.MustCompile(`^user_[0-9a-f]{12}$`)
	seen := make(map[string]bool)
	for i := 0; i < 100; i++ {
		account, err := RandomAccount()
		if err != nil {
			t.Fatalf("RandomAccount() error = %v, want nil", err)
		}
		if !pattern.MatchString(account) {
			t.Errorf("account %q does not match user_ + 12 hex chars", account)
		}
		if seen[account] {
			t.Errorf("duplicate account %q", account)
		}
		seen[account] = true
	}
}

func TestRandomPasswordFormat(t *testing.T) {
	for i := 0; i < 100; i++ {
		p, err := RandomPassword()
		if err != nil {
			t.Fatalf("RandomPassword() error = %v, want nil", err)
		}
		if len(p) != passwordLength {
			t.Errorf("password length = %d, want %d", len(p), passwordLength)
		}
		var hasLower, hasUpper, hasDigit bool
		for _, c := range p {
			switch {
			case strings.ContainsRune(lowerChars, c):
				hasLower = true
			case strings.ContainsRune(upperChars, c):
				hasUpper = true
			case strings.ContainsRune(digitChars, c):
				hasDigit = true
			default:
				t.Errorf("password %q contains invalid char %q", p, c)
			}
		}
		if !hasLower || !hasUpper || !hasDigit {
			t.Errorf("password %q missing required class (lower=%v upper=%v digit=%v)", p, hasLower, hasUpper, hasDigit)
		}
	}
}
