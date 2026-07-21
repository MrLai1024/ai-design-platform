<template>
  <div class="flex gap-1 mb-3">
    <button
      v-for="mode in modes" :key="mode.key"
      class="px-2 py-1 text-xs rounded border"
      :class="active === mode.key
        ? 'bg-blue-500 text-white border-blue-500'
        : 'bg-white text-gray-600 border-gray-300 hover:bg-gray-100'"
      @click="$emit('select', mode.key)"
    >{{ mode.label }}</button>
  </div>
</template>

<script setup lang="ts">
defineProps<{ active: string }>()
defineEmits<{ select: [mode: string] }>()

const modes = [
  { key: 'new', label: '🆕 新建' },
  { key: 'edit', label: '✏️ 编辑' },
  { key: 'append', label: '➕ 追加' },
]
</script>
