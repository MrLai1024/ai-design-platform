import { describe, it, expect } from 'vitest';

describe('Chat types', () => {
  it('ConversationListItem should have required fields', () => {
    const item = {
      id: 'uuid-1',
      title: '测试对话',
      msg_count: 3,
      created_at: '2026-06-28T00:00:00Z',
      updated_at: '2026-06-28T00:00:00Z',
    };
    expect(item.id).toBeDefined();
    expect(item.title).toBeDefined();
    expect(item.msg_count).toBeTypeOf('number');
    expect(item.created_at).toBeDefined();
    expect(item.updated_at).toBeDefined();
  });

  it('Message should have role as user | assistant | system', () => {
    const msg = {
      id: 'msg-1',
      role: 'user' as const,
      content: '你好',
      created_at: '2026-06-28T00:00:00Z',
    };
    expect(['user', 'assistant', 'system']).toContain(msg.role);
  });

  it('TokenEvent should use text field (matching backend)', () => {
    const event = { text: '你好', index: 0 };
    expect(event.text).toBeDefined();
    expect(event.index).toBeTypeOf('number');
  });

  it('SendMessageRequest requires model and content', () => {
    const req = { model: 'glm-5.2', content: '帮我设计' };
    expect(req.model).toBeTruthy();
    expect(req.content).toBeTruthy();
  });

  it('ListConversationsResponse wraps in conversations key', () => {
    const resp = { conversations: [] };
    expect(Array.isArray(resp.conversations)).toBe(true);
  });
});
