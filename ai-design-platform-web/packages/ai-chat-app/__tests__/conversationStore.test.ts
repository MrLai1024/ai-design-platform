import { describe, it, expect, beforeEach } from 'vitest';
import { setActivePinia, createPinia } from 'pinia';
import { useConversationStore } from '../src/stores/conversationStore';

const mockItems = [
  { id: '1', title: '设计登录页面', msg_count: 3, created_at: '2026-06-28T00:00:00Z', updated_at: '2026-06-28T01:00:00Z' },
  { id: '2', title: 'API 设计建议', msg_count: 1, created_at: '2026-06-27T00:00:00Z', updated_at: '2026-06-27T01:00:00Z' },
  { id: '3', title: '配色方案咨询', msg_count: 5, created_at: '2026-06-26T00:00:00Z', updated_at: '2026-06-26T01:00:00Z' },
];

describe('conversationStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it('should start with empty conversations', () => {
    const store = useConversationStore();
    expect(store.conversations).toHaveLength(0);
  });

  it('should set conversations', () => {
    const store = useConversationStore();
    store.setConversations(mockItems);
    expect(store.conversations).toHaveLength(3);
  });

  it('should add conversation to top', () => {
    const store = useConversationStore();
    store.setConversations([...mockItems]);
    store.addConversation({ id: '4', title: '新对话', msg_count: 0, created_at: '', updated_at: '' });
    expect(store.conversations[0].id).toBe('4');
  });

  it('should remove conversation by id', () => {
    const store = useConversationStore();
    store.setConversations([...mockItems]);
    store.removeConversation('1');
    expect(store.conversations).toHaveLength(2);
    expect(store.conversations.find((c: any) => c.id === '1')).toBeUndefined();
  });

  it('should filter by search query', () => {
    const store = useConversationStore();
    store.setConversations([...mockItems]);
    store.setSearchQuery('登录');
    expect(store.filteredConversations).toHaveLength(1);
    expect(store.filteredConversations[0].id).toBe('1');
  });

  it('should filter case-insensitively', () => {
    const store = useConversationStore();
    store.setConversations([...mockItems]);
    store.setSearchQuery('api');
    expect(store.filteredConversations).toHaveLength(1);
    expect(store.filteredConversations[0].title).toContain('API');
  });

  it('should toggle pin status', () => {
    const store = useConversationStore();
    store.setConversations([...mockItems]);
    store.togglePin('1');
    expect(store.pinnedIds.has('1')).toBe(true);
    store.togglePin('1');
    expect(store.pinnedIds.has('1')).toBe(false);
  });

  it('pinned conversations come before normal', () => {
    const store = useConversationStore();
    store.setConversations([...mockItems]);
    store.togglePin('3');
    const pinned = store.pinnedConversations;
    const normal = store.normalConversations;
    expect(pinned).toHaveLength(1);
    expect(pinned[0].id).toBe('3');
    expect(normal).toHaveLength(2);
  });

  it('should toggle archive status', () => {
    const store = useConversationStore();
    store.setConversations([...mockItems]);
    store.toggleArchive('2');
    expect(store.archivedIds.has('2')).toBe(true);
    const archived = store.archivedConversations;
    expect(archived).toHaveLength(1);
    expect(archived[0].id).toBe('2');
  });

  it('should update conversation title', () => {
    const store = useConversationStore();
    store.setConversations([...mockItems]);
    store.updateConversation('1', { title: '新标题' });
    expect(store.conversations.find((c: any) => c.id === '1')?.title).toBe('新标题');
  });

  it('should increment message count', () => {
    const store = useConversationStore();
    store.setConversations([...mockItems]);
    store.incrementMsgCount('1');
    expect(store.conversations.find((c: any) => c.id === '1')?.msg_count).toBe(4);
  });
});
