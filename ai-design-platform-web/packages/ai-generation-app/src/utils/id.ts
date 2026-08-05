// src/utils/id.ts

/** 生成消息/日志条目的短唯一 ID */
export function generateId(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 9)
}
