// Package migrations 内嵌数据库迁移 SQL,供启动时按文件名排序幂等执行。
package migrations

import "embed"

// FS 内嵌 migrations 目录下全部 .sql 文件。
//
//go:embed *.sql
var FS embed.FS
