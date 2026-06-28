import { http } from './request';
import type {
  Conversation,
  CreateConversationResponse,
  ListConversationsResponse,
} from '../types/chat';

/**
 * 创建新对话
 * POST /api/v1/conversations  body: { title }
 */
export function createConversation(title: string) {
  return http.post<CreateConversationResponse>('/v1/conversations', { title });
}

/**
 * 获取对话列表
 * GET /api/v1/conversations
 * 响应被 conversations 键包裹
 */
export function listConversations() {
  return http.get<ListConversationsResponse>('/v1/conversations');
}

/**
 * 获取单条对话（含消息列表）
 * GET /api/v1/conversations/:id
 */
export function getConversation(id: string) {
  return http.get<Conversation>(`/v1/conversations/${id}`);
}

/**
 * 删除对话
 * DELETE /api/v1/conversations/:id
 */
export function deleteConversation(id: string) {
  return http.delete(`/v1/conversations/${id}`);
}

/**
 * SSE 流式发送消息
 * POST /api/v1/conversations/:id/messages
 * 使用原生 fetch 以支持 ReadableStream 读取
 * 注意：请求体需要 model + content（均为必填）
 */
export function streamChat(
  conversationId: string,
  model: string,
  content: string,
  enableThinking: boolean = false,
) {
  return fetch(`/api/v1/conversations/${conversationId}/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model, content, enable_thinking: enableThinking }),
  });
}

/**
 * 取消生成
 * POST /api/v1/chat/cancel/:generation_id
 */
export function cancelGeneration(generationId: string) {
  return http.post(`/v1/chat/cancel/${generationId}`);
}
