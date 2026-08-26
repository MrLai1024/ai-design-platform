package handler

import (
	"github.com/gin-gonic/gin"
)

// 业务码表:HTTP 状态码保留 RESTful 语义,body 统一为信封格式 {code,msg,data}。
const (
	CodeSuccess      = 0     // 成功
	CodeParamError   = 40000 // 参数错误(400)
	CodeUserNotFound = 40001 // 用户不存在(404)
	CodeUnauthorized = 40100 // 未认证(401)
	CodeForbidden    = 40300 // 无权限(403)
	CodeNotFound     = 40400 // 资源不存在(404,团队/项目不存在等)
	CodeConflict     = 40900 // 冲突(409,重复加入等)
	CodeInternal     = 50000 // 内部错误(500)
)

// response 是统一响应信封:成功 code=0、msg=success;错误 code 为业务码、msg 为中文提示,data 恒为 null。
type response struct {
	Code int    `json:"code"`
	Msg  string `json:"msg"`
	Data any    `json:"data"`
}

// Success 写出成功信封 {code:0, msg:"success", data:业务数据};
// data 为 nil 时序列化为 null(如 join、删除等无业务数据的成功响应)。
func Success(c *gin.Context, status int, data any) {
	c.JSON(status, response{Code: CodeSuccess, Msg: "success", Data: data})
}

// Error 写出错误信封 {code:业务码, msg:中文提示, data:null}。
func Error(c *gin.Context, status int, code int, msg string) {
	c.JSON(status, response{Code: code, Msg: msg})
}
