import { describe, it, expect, beforeEach } from 'vitest';
import { setActivePinia, createPinia } from 'pinia';
import { useChatStore } from '../src/stores/chatStore';

describe('chatStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it('should start with empty state', () => {
    const store = useChatStore();
    expect(store.currentConversationId).toBeNull();
    expect(store.messages).toHaveLength(0);
    expect(store.isStreaming).toBe(false);
  });

  it('should select a conversation and set messages', () => {
    const store = useChatStore();
    const msgs = [
      { id: '1', role: 'user' as const, content: '你好', created_at: '' },
      { id: '2', role: 'assistant' as const, content: '你好！', created_at: '' },
    ];
    store.selectConversation('conv-1', msgs);
    expect(store.currentConversationId).toBe('conv-1');
    expect(store.messages).toHaveLength(2);
  });

  it('should append user message', () => {
    const store = useChatStore();
    store.appendMessage({ id: '1', role: 'user', content: '测试', created_at: '' });
    expect(store.messages).toHaveLength(1);
    expect(store.messages[0].role).toBe('user');
  });

  it('should append assistant message', () => {
    const store = useChatStore();
    store.appendMessage({ id: '1', role: 'assistant', content: '回复', created_at: '' });
    expect(store.messages[0].role).toBe('assistant');
  });

  it('should start streaming and accumulate content', () => {
    const store = useChatStore();
    store.startStreaming();
    expect(store.isStreaming).toBe(true);
    expect(store.streamingContent).toBe('');

    store.appendToken('你好');
    expect(store.streamingContent).toBe('你好');

    store.appendToken('世界');
    expect(store.streamingContent).toBe('你好世界');
  });

  it('should finish streaming and finalize message', () => {
    const store = useChatStore();
    store.startStreaming();
    store.appendToken('AI 回复内容');
    store.finishStreaming('msg-final');
    expect(store.isStreaming).toBe(false);
    expect(store.streamingContent).toBe('');
    expect(store.messages).toHaveLength(1);
    expect(store.messages[0].id).toBe('msg-final');
    expect(store.messages[0].role).toBe('assistant');
    expect(store.messages[0].content).toBe('AI 回复内容');
  });

  it('should handle stream error', () => {
    const store = useChatStore();
    store.startStreaming();
    store.appendToken('部分内容');
    store.setStreamError('网络错误');
    expect(store.streamError).toBe('网络错误');
    expect(store.streamingContent).toBe('部分内容');
  });

  it('displayMessages should include streaming content as virtual message', () => {
    const store = useChatStore();
    store.appendMessage({ id: '1', role: 'user', content: '提问', created_at: '' });
    store.startStreaming();
    store.appendToken('流式回复');
    expect(store.displayMessages).toHaveLength(2);
    expect(store.displayMessages[1].role).toBe('assistant');
    expect(store.displayMessages[1].content).toBe('流式回复');
    expect(store.displayMessages[1].id).toBe('__streaming__');
  });

  it('should cancel streaming', () => {
    const store = useChatStore();
    store.startStreaming();
    store.cancelStream();
    expect(store.isStreaming).toBe(false);
  });

  it('should clear input', () => {
    const store = useChatStore();
    store.inputText = 'test input';
    store.clearInput();
    expect(store.inputText).toBe('');
  });

  it('should reset state on conversation switch', () => {
    const store = useChatStore();
    store.selectConversation('conv-1', [
      { id: '1', role: 'user', content: 'msg', created_at: '' },
    ]);
    store.startStreaming();
    store.appendToken('streaming');
    store.selectConversation('conv-2', []);
    expect(store.streamingContent).toBe('');
    expect(store.isStreaming).toBe(false);
    expect(store.streamError).toBeNull();
    expect(store.currentConversationId).toBe('conv-2');
  });
});
