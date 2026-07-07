<!-- src/components/TabBar.vue -->
<script setup lang="ts">
import type { CodeViewTab } from '@/types/generation'

defineProps<{
  tabs: Array<{ key: CodeViewTab; label: string }>
  activeTab: CodeViewTab
}>()

const emit = defineEmits<{
  'select': [tab: CodeViewTab]
}>()
</script>

<template>
  <div class="tab-bar flex border-b border-gray-200 bg-gray-50">
    <button
      v-for="tab in tabs"
      :key="tab.key"
      class="px-4 py-2 text-sm font-medium transition-colors border-b-2 -mb-px"
      :class="activeTab === tab.key
        ? 'border-blue-500 text-blue-600'
        : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
      "
      @click="emit('select', tab.key)"
    >
      {{ tab.label }}
    </button>
  </div>
</template>
