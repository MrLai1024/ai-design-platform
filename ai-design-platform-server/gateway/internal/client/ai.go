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
