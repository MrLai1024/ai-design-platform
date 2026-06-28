import { defineStore } from 'pinia';
import { ref, computed } from 'vue';
import type { ConversationListItem } from '@ai-design/shared';

const PINNED_KEY = 'ai_chat_pinned_ids';
const ARCHIVED_KEY = 'ai_chat_archived_ids';

function loadIds(key: string): Set<string> {
  try {
    const raw = localStorage.getItem(key);
    return raw ? new Set(JSON.parse(raw)) : new Set();
  } catch {
    return new Set();
  }
}

function saveIds(key: string, ids: Set<string>) {
  localStorage.setItem(key, JSON.stringify([...ids]));
}

export const useConversationStore = defineStore('conversation', () => {
  const conversations = ref<ConversationListItem[]>([]);
  const searchQuery = ref('');
  const loading = ref(false);
  const pinnedIds = ref<Set<string>>(loadIds(PINNED_KEY));
  const archivedIds = ref<Set<string>>(loadIds(ARCHIVED_KEY));

  const filteredConversations = computed(() => {
    const q = searchQuery.value.toLowerCase().trim();
    if (!q) return conversations.value;
    return conversations.value.filter((c) =>
      c.title.toLowerCase().includes(q),
    );
  });

  const pinnedConversations = computed(() =>
    filteredConversations.value.filter(
      (c) => pinnedIds.value.has(c.id) && !archivedIds.value.has(c.id),
    ),
  );

  const normalConversations = computed(() =>
    filteredConversations.value.filter(
      (c) => !pinnedIds.value.has(c.id) && !archivedIds.value.has(c.id),
    ),
  );

  const archivedConversations = computed(() =>
    filteredConversations.value.filter((c) => archivedIds.value.has(c.id)),
  );

  function setConversations(items: ConversationListItem[]) {
    conversations.value = items;
  }

  function addConversation(item: ConversationListItem) {
    conversations.value.unshift(item);
  }

  function removeConversation(id: string) {
    conversations.value = conversations.value.filter((c) => c.id !== id);
    pinnedIds.value.delete(id);
    archivedIds.value.delete(id);
    persistPins();
    persistArchives();
  }

  function updateConversation(id: string, patch: Partial<ConversationListItem>) {
    const idx = conversations.value.findIndex((c) => c.id === id);
    if (idx !== -1) {
      conversations.value[idx] = { ...conversations.value[idx], ...patch };
    }
  }

  function incrementMsgCount(id: string) {
    const idx = conversations.value.findIndex((c) => c.id === id);
    if (idx !== -1) {
      conversations.value[idx].msg_count += 1;
    }
  }

  function setSearchQuery(q: string) {
    searchQuery.value = q;
  }

  function togglePin(id: string) {
    if (pinnedIds.value.has(id)) {
      pinnedIds.value.delete(id);
    } else {
      pinnedIds.value.add(id);
    }
    persistPins();
  }

  function toggleArchive(id: string) {
    if (archivedIds.value.has(id)) {
      archivedIds.value.delete(id);
    } else {
      archivedIds.value.add(id);
    }
    persistArchives();
  }

  function persistPins() {
    saveIds(PINNED_KEY, pinnedIds.value);
  }

  function persistArchives() {
    saveIds(ARCHIVED_KEY, archivedIds.value);
  }

  return {
    conversations,
    searchQuery,
    loading,
    pinnedIds,
    archivedIds,
    filteredConversations,
    pinnedConversations,
    normalConversations,
    archivedConversations,
    setConversations,
    addConversation,
    removeConversation,
    updateConversation,
    incrementMsgCount,
    setSearchQuery,
    togglePin,
    toggleArchive,
  };
});
