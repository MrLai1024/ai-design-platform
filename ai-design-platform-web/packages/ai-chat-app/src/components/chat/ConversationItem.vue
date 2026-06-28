<template>
  <div
    :class="[
      'group flex items-center justify-between px-3 py-2 rounded-md cursor-pointer transition-colors',
      isActive
        ? 'bg-indigo-600/20 text-indigo-200'
        : 'hover:bg-white/5 text-gray-300',
    ]"
    @click="$emit('select')"
    @contextmenu.prevent="showMenu = !showMenu"
  >
    <div class="truncate flex-1 text-sm" :title="item.title">
      {{ item.title }}
    </div>

    <span class="text-xs text-gray-500 ml-2 flex-shrink-0" :title="fullTime">
      {{ relativeTime }}
    </span>

    <div
      v-if="showMenu"
      class="absolute right-2 top-8 z-50 bg-gray-800 border border-gray-700 rounded-lg shadow-xl py-1 min-w-[140px]"
      @click.stop
    >
      <button
        v-if="!isArchived"
        class="w-full text-left px-3 py-1.5 text-sm hover:bg-white/10 text-gray-300"
        @click="$emit('pin'); showMenu = false"
      >
        {{ isPinned ? '📌 取消置顶' : '📌 置顶' }}
      </button>
      <button
        class="w-full text-left px-3 py-1.5 text-sm hover:bg-white/10 text-gray-300"
        @click="$emit('archive'); showMenu = false"
      >
        {{ isArchived ? '📂 取消归档' : '📦 归档' }}
      </button>
      <button
        class="w-full text-left px-3 py-1.5 text-sm hover:bg-white/10 text-red-400"
        @click="$emit('delete'); showMenu = false"
      >
        🗑 删除
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue';
import type { ConversationListItem } from '@ai-design/shared';

const props = defineProps<{
  item: ConversationListItem;
  isActive: boolean;
  isPinned: boolean;
  isArchived: boolean;
}>();

defineEmits<{
  select: [];
  pin: [];
  archive: [];
  delete: [];
}>();

const showMenu = ref(false);

function closeMenu() {
  showMenu.value = false;
}
onMounted(() => document.addEventListener('click', closeMenu));
onUnmounted(() => document.removeEventListener('click', closeMenu));

const fullTime = computed(() => new Date(props.item.updated_at).toLocaleString('zh-CN'));

const relativeTime = computed(() => {
  const diff = Date.now() - new Date(props.item.updated_at).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return '刚刚';
  if (mins < 60) return `${mins}分钟前`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}小时前`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}天前`;
  return new Date(props.item.updated_at).toLocaleDateString('zh-CN');
});
</script>
