package client

import (
	"context"
	"fmt"
	"io"
	"log/slog"

	pb "ai-design-platform/gen/go/ai/v1"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
)

// AIClient 封装了到 Python AI 服务的 gRPC 连接。
type AIClient struct {
	conn   *grpc.ClientConn
	genCli pb.GenerationServiceClient
}

// NewAIClient 创建连接到 AI 服务的新 gRPC 客户端。
func NewAIClient(ctx context.Context, addr string) (*AIClient, error) {
	conn, err := grpc.DialContext(ctx, addr,
		grpc.WithTransportCredentials(insecure.NewCredentials()),
		grpc.WithBlock(),
	)
	if err != nil {
		return nil, fmt.Errorf("failed to connect to AI service at %s: %w", addr, err)
	}

	slog.Info("Connected to AI service", "addr", addr)
	return &AIClient{
		conn:   conn,
		genCli: pb.NewGenerationServiceClient(conn),
	}, nil
}

// StreamGenerate 打开用于 AI 生成的服务端流式 gRPC 调用。
func (c *AIClient) StreamGenerate(
	ctx context.Context,
	req *pb.GenerateRequest,
) (pb.GenerationService_StreamGenerateClient, error) {
	stream, err := c.genCli.StreamGenerate(ctx, req)
	if err != nil {
		return nil, fmt.Errorf("StreamGenerate RPC failed: %w", err)
	}
	return stream, nil
}

// CancelGeneration 取消 AI 服务中正在进行的生成任务。
func (c *AIClient) CancelGeneration(ctx context.Context, generationID, reason string) error {
	_, err := c.genCli.CancelGeneration(ctx, &pb.CancelRequest{
		GenerationId: generationID,
		Reason:       reason,
	})
	return err
}

// CompileError mirrors one bundler error from the frontend preview.
type CompileError struct {
	File   string `json:"file"`
	Line   int32  `json:"line"`
	Column int32  `json:"column"`
	Text   string `json:"text"`
}

// ReportCompileFeedback 转发前端打包结果到 AI 服务。
func (c *AIClient) ReportCompileFeedback(ctx context.Context, generationID string, ok bool, errs []CompileError) (bool, error) {
	pbErrs := make([]*pb.CompileError, len(errs))
	for i, e := range errs {
		pbErrs[i] = &pb.CompileError{File: e.File, Line: e.Line, Column: e.Column, Text: e.Text}
	}
	resp, err := c.genCli.ReportCompileFeedback(ctx, &pb.CompileFeedbackRequest{
		GenerationId: generationID,
		Ok:           ok,
		Errors:       pbErrs,
	})
	if err != nil {
		return false, err
	}
	return resp.Received, nil
}

// RuntimeError mirrors one iframe-captured runtime error from the preview.
type RuntimeError struct {
	Type    string `json:"type"`    // "console_error" | "uncaught" | "unhandledrejection" | "network"
	Message string `json:"message"`
	Stack   string `json:"stack,omitempty"`
	URL     string `json:"url,omitempty"`
}

// ReportRuntimeFeedback 转发预览 iframe 的运行时错误到 AI 服务（Verifier L3 证据）。
// 替换语义：errors 为当前构建的快照；空批次 = 清空（新构建加载）。
func (c *AIClient) ReportRuntimeFeedback(ctx context.Context, generationID string, errs []RuntimeError) (bool, error) {
	pbErrs := make([]*pb.RuntimeError, len(errs))
	for i, e := range errs {
		pbErrs[i] = &pb.RuntimeError{Type: e.Type, Message: e.Message, Stack: e.Stack, Url: e.URL}
	}
	resp, err := c.genCli.ReportRuntimeFeedback(ctx, &pb.RuntimeFeedbackRequest{
		GenerationId: generationID,
		Errors:       pbErrs,
	})
	if err != nil {
		return false, err
	}
	return resp.Received, nil
}

// E2EEvidence mirrors the runner's per-case evidence (task group 6.3).
type E2EEvidence struct {
	DOMSnapshot    string   `json:"dom_snapshot,omitempty"`
	ConsoleErrors  []string `json:"console_errors,omitempty"`
	NetworkErrors  []string `json:"network_errors,omitempty"`
	ScreenshotNote string   `json:"screenshot_note,omitempty"`
}

// E2ECaseResult mirrors one executed E2E case (6.3/6.7). Status ∈ "" |
// "passed" | "failed" | "skipped_requires_browser".
type E2ECaseResult struct {
	CaseID     string      `json:"case_id"`
	Passed     bool        `json:"passed"`
	Error      string      `json:"error,omitempty"`
	Status     string      `json:"status,omitempty"`
	Screenshot string      `json:"screenshot,omitempty"`
	Evidence   *E2EEvidence `json:"evidence,omitempty"`
}

// ResumeAfterE2E 转发完整一轮 E2E 结果到 AI 服务：Test Diagnoser 三方分类 →
// e2e gate 路由（真实回归回功能实现节点）。返回服务器流（GraphEvents SSE）。
func (c *AIClient) ResumeAfterE2E(
	ctx context.Context,
	generationID string,
	results []E2ECaseResult,
) (pb.GenerationService_ResumeAfterE2EClient, error) {
	pbResults := make([]*pb.E2ECaseResult, len(results))
	for i, r := range results {
		pbRes := &pb.E2ECaseResult{
			CaseId:     r.CaseID,
			Passed:     r.Passed,
			Error:      r.Error,
			Status:     r.Status,
			Screenshot: r.Screenshot,
		}
		if r.Evidence != nil {
			pbRes.Evidence = &pb.E2EEvidence{
				DomSnapshot:    r.Evidence.DOMSnapshot,
				ConsoleErrors:  r.Evidence.ConsoleErrors,
				NetworkErrors:  r.Evidence.NetworkErrors,
				ScreenshotNote: r.Evidence.ScreenshotNote,
			}
		}
		pbResults[i] = pbRes
	}
	stream, err := c.genCli.ResumeAfterE2E(ctx, &pb.ResumeAfterE2ERequest{
		GenerationId: generationID,
		Results:      pbResults,
	})
	if err != nil {
		return nil, fmt.Errorf("ResumeAfterE2E RPC failed: %w", err)
	}
	return stream, nil
}

// ClassifyIntent 分类用户对话意图（Manager 意图路由）。
func (c *AIClient) ClassifyIntent(ctx context.Context, text, stage, generationID string) (string, string, error) {
	resp, err := c.genCli.ClassifyIntent(ctx, &pb.ClassifyIntentRequest{
		Text:         text,
		Stage:        stage,
		GenerationId: generationID,
	})
	if err != nil {
		return "", "", err
	}
	return resp.Intent, resp.Reason, nil
}

// BrainstormTurn 运行一轮议程驱动的澄清（任务组 3）。
// 首次调用不传 generationID → 创建会话并返回其 id；后续调用带上继续。
func (c *AIClient) BrainstormTurn(ctx context.Context, text, generationID, itemID string) (*pb.BrainstormTurnResponse, error) {
	resp, err := c.genCli.BrainstormTurn(ctx, &pb.BrainstormTurnRequest{
		Text:         text,
		GenerationId: generationID,
		ItemId:       itemID,
	})
	if err != nil {
		return nil, err
	}
	return resp, nil
}

// Close 关闭 gRPC 连接。
func (c *AIClient) Close() error {
	return c.conn.Close()
}

// ReceiveAll 从流中读取所有响应（用于测试）。
func ReceiveAll(stream pb.GenerationService_StreamGenerateClient) ([]*pb.GenerateResponse, error) {
	var responses []*pb.GenerateResponse
	for {
		resp, err := stream.Recv()
		if err == io.EOF {
			break
		}
		if err != nil {
			return responses, fmt.Errorf("stream receive error: %w", err)
		}
		responses = append(responses, resp)
	}
	return responses, nil
}
