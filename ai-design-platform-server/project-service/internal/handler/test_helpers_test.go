package handler

import (
	"encoding/json"
	"testing"
)

// handlerUserID 是 handler 测试用的固定用户 id。
const handlerUserID = "22222222-2222-2222-2222-222222222222"

// respEnvelope 是统一响应信封,Data 保持原始 JSON 以便二次解析业务数据。
type respEnvelope struct {
	Code int             `json:"code"`
	Msg  string          `json:"msg"`
	Data json.RawMessage `json:"data"`
}

// unmarshalEnvelope 解析统一信封并断言成功字段(code=0、msg=success)。
func unmarshalEnvelope(t *testing.T, body []byte) respEnvelope {
	t.Helper()
	var env respEnvelope
	if err := json.Unmarshal(body, &env); err != nil {
		t.Fatalf("unmarshal envelope: %v", err)
	}
	if env.Code != 0 {
		t.Errorf("envelope code = %d, want 0 (success), body = %s", env.Code, body)
	}
	if env.Msg != "success" {
		t.Errorf("envelope msg = %q, want %q", env.Msg, "success")
	}
	return env
}
