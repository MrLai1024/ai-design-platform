<!-- src/components/StepProgress.vue -->
<script setup lang="ts">
import type { StepNode, Stage } from '@/types/generation'

const props = defineProps<{
  nodes: StepNode[]
  currentStage: Stage
  isRollingBack?: boolean
  rollbackTarget?: string
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
          'connector-rollback': props.isRollingBack,
        }"
      />
      <!-- 节点 -->
      <button
        class="flex flex-col items-center gap-1.5 transition-colors"
        :class="node.status !== 'pending' ? 'cursor-pointer hover:opacity-80' : 'cursor-default'"
        :disabled="node.status === 'pending'"
        @click="emit('node-click', node)"
      >
        <span
          class="w-8 h-8 rounded-full border-2 flex items-center justify-center text-xs font-bold transition-all"
          :class="{
            'bg-green-500 border-green-500': node.status === 'done',
            'bg-blue-500 border-blue-500 animate-pulse': node.status === 'active',
            'bg-gray-300 border-gray-300': node.status === 'pending',
            'node-rollback': props.rollbackTarget === node.key,
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

<style scoped>
.connector-rollback {
  background: linear-gradient(90deg, #f87171, #fbbf24);
  animation: rollback-pulse 0.6s ease-in-out infinite alternate;
}

.node-rollback {
  border-color: #f59e0b !important;
  box-shadow: 0 0 8px rgba(245, 158, 11, 0.5);
  animation: rollback-blink 0.5s ease-in-out infinite alternate;
}

@keyframes rollback-pulse {
  0% { opacity: 0.6; }
  100% { opacity: 1; }
}

@keyframes rollback-blink {
  0% { transform: scale(1); }
  100% { transform: scale(1.15); }
}
</style>
