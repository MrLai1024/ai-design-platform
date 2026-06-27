import { describe, it, expect } from 'vitest';
import { parseSSEEvent } from '../src/composables/useChatStream';

describe('useChatStream - SSE parsing', () => {
  it('parses a token event', () => {
    const raw = 'event: token\ndata: {"text":"你好","index":0}';
    const event = parseSSEEvent(raw);
    expect(event).not.toBeNull();
    expect(event!.type).toBe('token');
    expect(event!.text).toBe('你好');
    expect(event!.index).toBe(0);
  });

  it('parses meta event', () => {
    const raw = 'event: meta\ndata: {"generation_id":"gen-1","conversation_id":"conv-1"}';
    const event = parseSSEEvent(raw);
    expect(event).not.toBeNull();
    expect(event!.type).toBe('meta');
    expect(event!.generation_id).toBe('gen-1');
  });

  it('parses done event', () => {
    const raw = 'event: done\ndata: [DONE]';
    const event = parseSSEEvent(raw);
    expect(event).not.toBeNull();
    expect(event!.type).toBe('done');
  });

  it('parses complete event (JSON string data)', () => {
    const raw = 'event: complete\ndata: {"finish_reason":"stop"}';
    const event = parseSSEEvent(raw);
    expect(event).not.toBeNull();
    expect(event!.type).toBe('complete');
    expect(event!.finish_reason).toBe('stop');
  });

  it('parses error event', () => {
    const raw = 'event: error\ndata: {"code":"TIMEOUT","message":"模型超时"}';
    const event = parseSSEEvent(raw);
    expect(event).not.toBeNull();
    expect(event!.type).toBe('error');
    expect(event!.message).toBe('模型超时');
  });

  it('returns null for empty string', () => {
    expect(parseSSEEvent('')).toBeNull();
  });

  it('returns null for incomplete JSON data', () => {
    const raw = 'event: token\ndata: {"text":"partial';
    expect(parseSSEEvent(raw)).toBeNull();
  });

  it('returns null for missing event type', () => {
    const raw = 'data: {"text":"hello"}';
    expect(parseSSEEvent(raw)).toBeNull();
  });
});
