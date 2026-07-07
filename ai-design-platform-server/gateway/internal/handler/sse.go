package handler

import (
	"encoding/json"
	"fmt"

	"github.com/gin-gonic/gin"
)

// writeSSE 写入纯 data: 字段的 SSE 帧（兼容 Chrome DevTools EventStream 解析）。
// 事件类型通过 JSON 中的 _t 字段区分，不使用 event: 行。
func writeSSE(c *gin.Context, event string, data interface{}) {
	var dataStr string
	switch v := data.(type) {
	case string:
		// 字符串直接作为 data 值（如 [DONE]）
		dataStr = v
	default:
		b, _ := json.Marshal(data)
		dataStr = string(b)
	}
	fmt.Fprintf(c.Writer, "data: %s\n\n", dataStr)
	c.Writer.Flush()
}
