<!-- src/components/MultiAgentPanel.vue -->
<script setup lang="ts">
import { useGenerationStore } from '@/stores/generation'

const store = useGenerationStore()

function statusBadge(status: string): string {
  switch (status) {
    case 'running': return 'bg-blue-100 text-blue-700'
    case 'done': return 'bg-green-100 text-green-700'
    default: return 'bg-gray-100 text-gray-500'
  }
}

function sevBadge(severity: string): string {
  switch (severity) {
    case 'critical': return 'bg-red-100 text-red-700'
    case 'high': return 'bg-orange-100 text-orange-700'
    case 'medium': return 'bg-yellow-100 text-yellow-700'
    case 'low': return 'bg-blue-100 text-blue-700'
    default: return 'bg-gray-100 text-gray-500'
  }
}
</script>

<template>
  <div class="p-3 space-y-3">
    <div class="text-sm font-medium text-gray-700">🔍 多维度代码审查</div>

    <div class="grid grid-cols-2 gap-3">
      <div
        v-for="agent in store.reviewAgents"
        :key="agent.key"
        class="border rounded-lg p-3 bg-white"
      >
        <div class="flex items-center justify-between mb-2">
          <span class="text-sm font-medium">
            {{ agent.icon }} {{ agent.name }}
          </span>
          <span class="text-xs px-1.5 py-0.5 rounded-full" :class="statusBadge(agent.status)">
            {{ agent.status === 'running' ? '分析中' : agent.status === 'done' ? '完成' : '等待' }}
          </span>
        </div>

        <div v-if="agent.findings.length > 0" class="space-y-1">
          <div
            v-for="(f, i) in agent.findings"
            :key="i"
            class="text-xs border-l-2 pl-2"
            :class="{
              'border-red-500': f.severity === 'critical',
              'border-orange-400': f.severity === 'high',
              'border-yellow-400': f.severity === 'medium',
              'border-blue-400': f.severity === 'low',
            }"
          >
            <div class="flex items-center gap-1">
              <span class="px-1 py-0.5 rounded text-[10px]" :class="sevBadge(f.severity)">{{ f.severity }}</span>
              <strong>{{ f.title }}</strong>
            </div>
            <div class="text-gray-500 mt-0.5">{{ f.file }}:{{ f.line }}</div>
          </div>
        </div>

        <div v-else-if="agent.status === 'done'" class="text-xs text-green-600">
          ✓ 未发现问题
        </div>

        <div v-else-if="agent.status === 'running'" class="text-xs text-blue-500 animate-pulse">
          分析中...
        </div>

        <div v-else class="text-xs text-gray-400">
          等待开始
        </div>
      </div>
    </div>

    <div v-if="store.reviewAgents.some(a => a.status === 'done')" class="text-sm bg-gray-100 rounded p-2">
      共发现
      <strong>{{ store.reviewIssueSummary.total }}</strong> 个问题：
      <span v-if="store.reviewIssueSummary.critical > 0" class="text-red-600 ml-1">
        🔴 {{ store.reviewIssueSummary.critical }} critical
      </span>
      <span v-if="store.reviewIssueSummary.high > 0" class="text-orange-600 ml-1">
        🟠 {{ store.reviewIssueSummary.high }} high
      </span>
    </div>
  </div>
</template>
