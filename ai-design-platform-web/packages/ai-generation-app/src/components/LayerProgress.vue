<template>
  <div class="flex items-center gap-2 text-sm">
    <div v-for="(layer, idx) in layers" :key="idx" class="flex items-center">
      <span :class="{
        'w-2 h-2 rounded-full': true,
        'bg-blue-500': layer.status === 'active',
        'bg-green-500': layer.status === 'done',
        'bg-gray-300': layer.status === 'pending',
      }" />
      <span :class="{
        'ml-1': true,
        'text-blue-600 font-medium': layer.status === 'active',
        'text-gray-400': layer.status === 'pending',
        'text-green-600': layer.status === 'done',
      }">{{ layer.label }}</span>
      <span v-if="idx < layers.length - 1" class="mx-1 text-gray-300">→</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useGenerationStore } from '@/stores/generation'

const store = useGenerationStore()

const layers = computed(() => {
  const status = store.requirementsState?.layer_status ?? {}
  return [
    { label: '愿景对齐', status: status['1'] ?? 'pending' },
    { label: '功能分解', status: status['2'] ?? 'pending' },
    { label: '细节补充', status: status['3'] ?? 'pending' },
  ]
})
</script>
