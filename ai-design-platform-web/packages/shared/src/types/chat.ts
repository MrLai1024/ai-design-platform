/** 对话列表项（不含消息体），对应后端 ConversationListItem */
export interface ConversationListItem {
  id: string;
  title: string;
  msg_count: number;
  created_at: string;
  updated_at: string;
}

/** 单条消息，对应后端 Message */
export interface Message {
  id: string;
  role: 'system' | 'user' | 'assistant';
  content: string;
  created_at: string;
}

/** 完整对话（含消息列表），对应后端 Conversation */
export interface Conversation {
  id: string;
  title: string;
  messages: Message[];
  created_at: string;
  updated_at: string;
}

// ── SSE 事件类型 ──

/** SSE 事件类型 */
export type StreamEventType = 'meta' | 'token' | 'tool_call' | 'complete' | 'error' | 'done';

/** SSE token 事件 — 后端字段名是 text */
export interface TokenEvent {
  text: string;
  index: number;
}

/** SSE tool_call 事件 */
export interface ToolCallEvent {
  id: string;
  name: string;
  arguments: string;
}

/** SSE meta 事件 */
export interface MetaEvent {
  generation_id: string;
  conversation_id?: string;
  message_id?: string;
}

/** SSE error 事件 */
export interface ErrorEvent {
  message: string;
  code?: string;
}

/** SSE complete 事件 — data 是 JSON 字符串，需二次 parse */
export interface CompleteEvent {
  finish_reason: string;
}

/** SSE 事件联合类型 */
export interface StreamEvents {
  meta: MetaEvent;
  token: TokenEvent;
  tool_call: ToolCallEvent;
  complete: CompleteEvent;
  error: ErrorEvent;
  done: '[DONE]';
}

// ── 请求/响应类型 ──

/** 发送消息请求 — model + content 均为必填 */
export interface SendMessageRequest {
  model: string;
  content: string;
  enable_thinking?: boolean;
}

/** 创建对话响应（后端返回） */
export interface CreateConversationResponse {
  id: string;
  title: string;
  created_at: string;
}

/** 对话列表响应 — 后端用 conversations 键包裹 */
export interface ListConversationsResponse {
  conversations: ConversationListItem[];
}
