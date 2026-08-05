package client

import (
	"context"
	"testing"

	pb "ai-design-platform/gen/go/ai/v1"

	"google.golang.org/grpc"
)

// fakeGenCli — 白盒测试桩：记录 runtime feedback 请求。
type fakeGenCli struct {
	received *pb.RuntimeFeedbackRequest
}

func (f *fakeGenCli) StreamGenerate(ctx context.Context, in *pb.GenerateRequest, opts ...grpc.CallOption) (pb.GenerationService_StreamGenerateClient, error) {
	return nil, nil
}
func (f *fakeGenCli) CancelGeneration(ctx context.Context, in *pb.CancelRequest, opts ...grpc.CallOption) (*pb.CancelResponse, error) {
	return &pb.CancelResponse{}, nil
}
func (f *fakeGenCli) ReportCompileFeedback(ctx context.Context, in *pb.CompileFeedbackRequest, opts ...grpc.CallOption) (*pb.CompileFeedbackResponse, error) {
	return &pb.CompileFeedbackResponse{}, nil
}
func (f *fakeGenCli) ClassifyIntent(ctx context.Context, in *pb.ClassifyIntentRequest, opts ...grpc.CallOption) (*pb.ClassifyIntentResponse, error) {
	return &pb.ClassifyIntentResponse{}, nil
}
func (f *fakeGenCli) BrainstormTurn(ctx context.Context, in *pb.BrainstormTurnRequest, opts ...grpc.CallOption) (*pb.BrainstormTurnResponse, error) {
	return &pb.BrainstormTurnResponse{}, nil
}
func (f *fakeGenCli) ReportRuntimeFeedback(ctx context.Context, in *pb.RuntimeFeedbackRequest, opts ...grpc.CallOption) (*pb.RuntimeFeedbackResponse, error) {
	f.received = in
	return &pb.RuntimeFeedbackResponse{Received: true}, nil
}
func (f *fakeGenCli) ResumeAfterE2E(ctx context.Context, in *pb.ResumeAfterE2ERequest, opts ...grpc.CallOption) (pb.GenerationService_ResumeAfterE2EClient, error) {
	return nil, nil
}

func TestReportRuntimeFeedback(t *testing.T) {
	fake := &fakeGenCli{}
	c := &AIClient{genCli: fake}

	received, err := c.ReportRuntimeFeedback(context.Background(), "gen-5b-1", []RuntimeError{
		{Type: "console_error", Message: "Cannot read 'x'"},
		{Type: "uncaught", Message: "boom", Stack: "at f (a.vue:1)", URL: "src/App.vue"},
	})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !received {
		t.Fatal("expected received=true")
	}
	if fake.received == nil {
		t.Fatal("expected runtime feedback forwarded to AI service")
	}
	if fake.received.GenerationId != "gen-5b-1" {
		t.Fatalf("unexpected generation id: %s", fake.received.GenerationId)
	}
	if len(fake.received.Errors) != 2 {
		t.Fatalf("expected 2 errors, got %d", len(fake.received.Errors))
	}
	if fake.received.Errors[0].Type != "console_error" || fake.received.Errors[0].Message != "Cannot read 'x'" {
		t.Fatalf("unexpected error mapping: %+v", fake.received.Errors[0])
	}
	if fake.received.Errors[1].Url != "src/App.vue" || fake.received.Errors[1].Stack != "at f (a.vue:1)" {
		t.Fatalf("unexpected stack/url mapping: %+v", fake.received.Errors[1])
	}
}

func TestReportRuntimeFeedbackEmptyBatch(t *testing.T) {
	fake := &fakeGenCli{}
	c := &AIClient{genCli: fake}

	received, err := c.ReportRuntimeFeedback(context.Background(), "gen-5b-2", nil)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !received {
		t.Fatal("expected received=true")
	}
	if fake.received == nil || fake.received.GenerationId != "gen-5b-2" || len(fake.received.Errors) != 0 {
		t.Fatalf("unexpected empty-batch mapping: %+v", fake.received)
	}
}
