<!-- src/components/StepProgress.vue -->
<script setup lang="ts">
import type { StepNode, Stage } from '@/types/generation'

defineProps<{
  nodes: StepNode[]
  currentStage: Stage
}>()

const emit = defineEmits<{
  'node-click': [node: StepNode]
}>()
</script>

<template>
  <div class="step-progress flex items-center justify-center gap-0 px-6 py-4 bg-gray-50 border-b border-gray-200">
    <template v-for="(node, index) in nodes" :key="node.key">
      <!-- 连线（非首节点） -->
      <div
        v-if="index > 0"
        class="flex-1 h-0.5 mx-2 min-w-[40px]"
        :class="{
          'bg-green-400': nodes[index - 1]!.status === 'done' && (node.status === 'done' || node.status === 'active'),
          'bg-gray-300': !(nodes[index - 1]!.status === 'done' && (node.status === 'done' || node.status === 'active')),
        }"
      />
      <!-- 节点 -->
      <button
        class="flex flex-col items-center gap-1.5 transition-colors"
        :class="node.status === 'done' ? 'cursor-pointer hover:opacity-80' : 'cursor-default'"
        :disabled="node.status !== 'done'"
        @click="emit('node-click', node)"
      >
        <span
          class="w-8 h-8 rounded-full border-2 flex items-center justify-center text-xs font-bold transition-all"
          :class="{
            'bg-green-500 border-green-500': node.status === 'done',
            'bg-blue-500 border-blue-500 animate-pulse': node.status === 'active',
            'bg-gray-300 border-gray-300': node.status === 'pending',
          }"
        >
          <span v-if="node.status === 'done'">✓</span>
          <span v-else>{{ index + 1 }}</span>
        </span>
        <span
          class="text-xs whitespace-nowrap font-medium"
          :class="{
            'text-green-600': node.status === 'done',
            'text-blue-600 font-semibold': node.status === 'active',
            'text-gray-400': node.status === 'pending',
          }"
        >
          {{ node.label }}
        </span>
      </button>
    </template>
  </div>
</template>
