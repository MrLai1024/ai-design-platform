package handler

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
)

// CompileRequest 是前端/后端发起的编译请求（转发到 node-compiler 服务）。
type CompileRequest struct {
	ProjectRoot string `json:"project_root" binding:"required"`
	Full        bool   `json:"full"`
	Entry       string `json:"entry,omitempty"`
}

// CompileError 是编译错误的结构化描述。
type CompileError struct {
	File    string `json:"file"`
	Line    int    `json:"line"`
	Column  int    `json:"column"`
	Message string `json:"message"`
	Source  string `json:"source"`
}

// CompileHandler 代理 node-compiler 服务的编译请求。
type CompileHandler struct {
	nodeCompilerAddr string
	httpClient       *http.Client
}

func NewCompileHandler(nodeCompilerAddr string) *CompileHandler {
	return &CompileHandler{
		nodeCompilerAddr: nodeCompilerAddr,
		httpClient:       &http.Client{Timeout: 120 * time.Second},
	}
}

// SubmitCompile 处理 POST /api/v1/generation/compile
// 转发到 node-compiler：esbuild 语法/import 校验 + vue-tsc 类型检查（full）。
func (h *CompileHandler) SubmitCompile(c *gin.Context) {
	var req CompileRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	payload, err := json.Marshal(req)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	url := "http://" + h.nodeCompilerAddr + "/compile"
	resp, err := h.httpClient.Post(url, "application/json", bytes.NewReader(payload))
	if err != nil {
		c.JSON(http.StatusBadGateway, gin.H{
			"ok":    false,
			"error": "node-compiler 服务不可达：" + err.Error(),
		})
		return
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"ok": false, "error": err.Error()})
		return
	}
	c.Data(resp.StatusCode, "application/json", body)
}
