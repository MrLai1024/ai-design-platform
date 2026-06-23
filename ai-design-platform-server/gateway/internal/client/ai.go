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

// AIClient wraps the gRPC connection to the Python AI service.
type AIClient struct {
	conn   *grpc.ClientConn
	genCli pb.GenerationServiceClient
}

// NewAIClient creates a new gRPC client connected to the AI service.
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

// StreamGenerate opens a server-streaming gRPC call for AI generation.
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

// CancelGeneration cancels an in-progress generation in the AI service.
func (c *AIClient) CancelGeneration(ctx context.Context, generationID, reason string) error {
	_, err := c.genCli.CancelGeneration(ctx, &pb.CancelRequest{
		GenerationId: generationID,
		Reason:       reason,
	})
	return err
}

// Close shuts down the gRPC connection.
func (c *AIClient) Close() error {
	return c.conn.Close()
}

// ReceiveAll reads all responses from a stream (for testing).
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
