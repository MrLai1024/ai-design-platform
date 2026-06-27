import { ref } from 'vue';
import {
  createConversation,
  listConversations,
  getConversation,
  deleteConversation,
} from '../api/chat';
import type {
  Conversation,
  ConversationListItem,
} from '../types/chat';

/**
 * 对话 CRUD composable。
 * 包装 API 调用，统一返回 { data, error, loading } 结构。
 */
export function useConversation() {
  const loading = ref(false);
  const error = ref<string | null>(null);
  const conversations = ref<ConversationListItem[]>([]);
  const currentConversation = ref<Conversation | null>(null);

  async function fetchList() {
    loading.value = true;
    error.value = null;
    try {
      const res = await listConversations();
      // 响应被 conversations 键包裹
      conversations.value = (res as unknown as { conversations: ConversationListItem[] }).conversations || [];
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : '获取对话列表失败';
    } finally {
      loading.value = false;
    }
  }

  async function fetchConversation(id: string) {
    loading.value = true;
    error.value = null;
    try {
      currentConversation.value = await getConversation(id) as unknown as Conversation;
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : '获取对话失败';
    } finally {
      loading.value = false;
    }
  }

  async function create(title: string): Promise<Conversation | null> {
    loading.value = true;
    error.value = null;
    try {
      const res = await createConversation(title) as unknown as Conversation;
      // 乐观添加到列表
      conversations.value.unshift({
        id: res.id,
        title: res.title || title,
        msg_count: 0,
        created_at: res.created_at || new Date().toISOString(),
        updated_at: res.created_at || new Date().toISOString(),
      });
      return res;
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : '创建对话失败';
      return null;
    } finally {
      loading.value = false;
    }
  }

  async function remove(id: string): Promise<boolean> {
    error.value = null;
    try {
      await deleteConversation(id);
      // 乐观移除
      conversations.value = conversations.value.filter((c) => c.id !== id);
      return true;
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : '删除对话失败';
      return false;
    }
  }

  return {
    conversations,
    currentConversation,
    loading,
    error,
    fetchList,
    fetchConversation,
    create,
    remove,
  };
}
