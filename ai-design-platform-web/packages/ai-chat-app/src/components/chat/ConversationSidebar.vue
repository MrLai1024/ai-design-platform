<template>
  <aside class="w-[260px] h-full bg-gray-900 border-r border-gray-800 flex flex-col flex-shrink-0">
    <div class="p-3">
      <button
        class="w-full py-2 px-4 bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium rounded-lg transition-colors"
        @click="$emit('newChat')"
      >
        + 新建对话
      </button>
    </div>

    <div class="px-3 pb-2">
      <input
        v-model="store.searchQuery"
        type="text"
        placeholder="搜索对话..."
        class="w-full bg-gray-800 border border-gray-700 rounded-md px-3 py-1.5 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-indigo-500 transition-colors"
        @input="store.setSearchQuery(($event.target as HTMLInputElement).value)"
      />
    </div>

    <div class="flex-1 overflow-y-auto px-2 pb-2 space-y-1">
      <template v-if="store.pinnedConversations.length">
        <p class="px-2 py-1 text-xs text-gray-500 uppercase tracking-wider">置顶</p>
        <ConversationItem
          v-for="conv in store.pinnedConversations"
          :key="conv.id"
          :item="conv"
          :is-active="activeId === conv.id"
          :is-pinned="true"
          :is-archived="false"
          @select="$emit('select', conv.id)"
          @pin="store.togglePin(conv.id)"
          @archive="store.toggleArchive(conv.id)"
          @delete="handleDelete(conv.id)"
        />
      </template>

      <template v-if="store.normalConversations.length">
        <p
          v-if="store.pinnedConversations.length"
          class="px-2 py-1 text-xs text-gray-500 uppercase tracking-wider"
        >
          对话
        </p>
        <ConversationItem
          v-for="conv in store.normalConversations"
          :key="conv.id"
          :item="conv"
          :is-active="activeId === conv.id"
          :is-pinned="false"
          :is-archived="false"
          @select="$emit('select', conv.id)"
          @pin="store.togglePin(conv.id)"
          @archive="store.toggleArchive(conv.id)"
          @delete="handleDelete(conv.id)"
        />
      </template>

      <template v-if="store.archivedConversations.length">
        <p
          class="px-2 py-1 text-xs text-gray-500 uppercase tracking-wider cursor-pointer hover:text-gray-300"
          @click="showArchived = !showArchived"
        >
          {{ showArchived ? '▾' : '▸' }} 归档 ({{ store.archivedConversations.length }})
        </p>
        <template v-if="showArchived">
          <ConversationItem
            v-for="conv in store.archivedConversations"
            :key="conv.id"
            :item="conv"
            :is-active="activeId === conv.id"
            :is-pinned="false"
            :is-archived="true"
            @select="$emit('select', conv.id)"
            @archive="store.toggleArchive(conv.id)"
            @delete="handleDelete(conv.id)"
          />
        </template>
      </template>

      <div
        v-if="store.conversations.length === 0 && !store.loading"
        class="text-center text-gray-500 text-sm py-8"
      >
        暂无对话
      </div>

      <div v-if="store.loading" class="text-center text-gray-500 text-sm py-8">加载中...</div>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import { useConversationStore } from '@/stores/conversationStore';
import ConversationItem from './ConversationItem.vue';

defineProps<{ activeId: string | null }>();

defineEmits<{
  select: [id: string];
  newChat: [];
  delete: [id: string];
}>();

const store = useConversationStore();
const showArchived = ref(false);

function handleDelete(id: string) {
  if (confirm('确认删除该对话？')) {
    store.removeConversation(id);
  }
}
</script>
