<!-- src/components/ToolTracePanel.vue -->
<script setup lang="ts">
import { useGenerationStore } from '@/stores/generation'

const store = useGenerationStore()

function statusIcon(status: string): string {
  switch (status) {
    case 'running': return '🔄'
    case 'done': return '✅'
    case 'error': return '❌'
    default: return '⏳'
  }
}

function formatToolName(tool: string): string {
  const map: Record<string, string> = {
    create_file: '创建文件',
    write_code: '写入代码',
    delete_file: '删除文件',
    compile_project: '编译检查',
    get_compile_errors: '获取错误',
    use_skill: 'Skill 模板',
    list_skills: '列出模板',
    mcp_query: 'MCP 查询',
  }
  return map[tool] || tool
}

function handleEntryClick(index: number): void {
  const entry = store.toolTraces[index]
  if (!entry) return
  if (entry.args?.path && store.files.has(entry.args.path)) {
    store.setActiveFile(entry.args.path)
    store.setCodeViewTab('files')
  }
}
</script>

<template>
  <div class="h-full overflow-y-auto p-3 bg-gray-50">
    <div class="text-sm font-medium text-gray-700 mb-2">
      🔧 工具调用链
      <span class="text-xs text-gray-400 ml-2">
        {{ Object.keys(store.generatedFiles).length }} 文件已生成
      </span>
    </div>

    <div v-if="store.toolTraces.length === 0" class="text-center text-gray-400 mt-8 text-sm">
      等待工具调用...
    </div>

    <div class="space-y-1">
      <div
        v-for="(entry, idx) in store.toolTraces"
        :key="entry.id"
        class="flex items-center gap-2 px-2 py-1.5 text-xs rounded hover:bg-gray-100 cursor-pointer transition-colors"
        :class="{ 'opacity-50': entry.status === 'error' }"
        @click="handleEntryClick(idx)"
      >
        <span>{{ statusIcon(entry.status) }}</span>
        <span class="font-mono text-blue-600">{{ formatToolName(entry.tool) }}</span>
        <span v-if="entry.args?.path" class="text-gray-500">→ {{ entry.args.path }}</span>
        <span v-if="entry.args?.name" class="text-purple-600">→ {{ entry.args.name }}</span>
        <span v-if="entry.summary" class="text-gray-400 ml-auto truncate max-w-[200px]">{{ entry.summary }}</span>
      </div>
    </div>
  </div>
</template>
