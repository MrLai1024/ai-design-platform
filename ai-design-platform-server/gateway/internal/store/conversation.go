package store

import (
	"sort"
	"sync"
	"time"
)

// Message 表示对话中的单条消息。
type Message struct {
	ID        string    `json:"id"`
	Role      string    `json:"role"` // "system"（系统）| "user"（用户）| "assistant"（助手）
	Content   string    `json:"content"`
	CreatedAt time.Time `json:"created_at"`
}

// Conversation 表示带有消息的聊天对话。
type Conversation struct {
	ID        string    `json:"id"`
	Title     string    `json:"title"`
	Messages  []Message `json:"messages"`
	CreatedAt time.Time `json:"created_at"`
	UpdatedAt time.Time `json:"updated_at"`
}

// ConversationListItem 是对话的摘要（不包含消息）。
type ConversationListItem struct {
	ID        string    `json:"id"`
	Title     string    `json:"title"`
	MsgCount  int       `json:"msg_count"`
	CreatedAt time.Time `json:"created_at"`
	UpdatedAt time.Time `json:"updated_at"`
}

// ConversationStore 是一个线程安全的内存对话存储。
type ConversationStore struct {
	mu   sync.RWMutex
	data map[string]*Conversation
}

// NewConversationStore 创建一个新的内存对话存储。
func NewConversationStore() *ConversationStore {
	return &ConversationStore{
		data: make(map[string]*Conversation),
	}
}

// Create 创建一个带有可选标题的新对话。
func (s *ConversationStore) Create(id, title string) *Conversation {
	s.mu.Lock()
	defer s.mu.Unlock()

	now := time.Now()
	if title == "" {
		title = "New Conversation"
	}
	conv := &Conversation{
		ID:        id,
		Title:     title,
		Messages:  make([]Message, 0),
		CreatedAt: now,
		UpdatedAt: now,
	}
	s.data[id] = conv
	return s.copyConv(conv)
}

// Get 根据 ID 返回对话，如果未找到则返回 nil。
func (s *ConversationStore) Get(id string) *Conversation {
	s.mu.RLock()
	defer s.mu.RUnlock()

	conv, ok := s.data[id]
	if !ok {
		return nil
	}
	return s.copyConv(conv)
}

// List 返回所有对话，按最近更新时间排序。
func (s *ConversationStore) List() []ConversationListItem {
	s.mu.RLock()
	defer s.mu.RUnlock()

	items := make([]ConversationListItem, 0, len(s.data))
	for _, c := range s.data {
		items = append(items, ConversationListItem{
			ID:        c.ID,
			Title:     c.Title,
			MsgCount:  len(c.Messages),
			CreatedAt: c.CreatedAt,
			UpdatedAt: c.UpdatedAt,
		})
	}
	sort.Slice(items, func(i, j int) bool {
		return items[i].UpdatedAt.After(items[j].UpdatedAt)
	})
	return items
}

// AddMessage 向对话追加一条消息。返回包含已设置 ID 的更新后消息。
func (s *ConversationStore) AddMessage(convID, id, role, content string) (*Conversation, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	conv, ok := s.data[convID]
	if !ok {
		return nil, nil
	}

	now := time.Now()
	msg := Message{
		ID:        id,
		Role:      role,
		Content:   content,
		CreatedAt: now,
	}
	conv.Messages = append(conv.Messages, msg)
	conv.UpdatedAt = now
	// 从第一条用户消息自动生成标题
	if role == "user" && conv.Title == "New Conversation" {
		runes := []rune(content)
		if len(runes) > 30 {
			conv.Title = string(runes[:30]) + "..."
		} else {
			conv.Title = content
		}
	}
	return s.copyConv(conv), nil
}

// Delete 删除一个对话。如果存在则返回 true。
func (s *ConversationStore) Delete(id string) bool {
	s.mu.Lock()
	defer s.mu.Unlock()

	_, ok := s.data[id]
	if ok {
		delete(s.data, id)
	}
	return ok
}

// copyConv 返回对话的浅拷贝（深拷贝 Messages 切片）。
func (s *ConversationStore) copyConv(c *Conversation) *Conversation {
	cp := *c
	cp.Messages = make([]Message, len(c.Messages))
	copy(cp.Messages, c.Messages)
	return &cp
}
