<!-- src/components/FileTreeNode.vue — recursive tree node for FileExplorer -->
<script setup lang="ts">
interface TreeNode {
  name: string
  path: string
  isDir: boolean
  children: TreeNode[]
}

const props = defineProps<{
  node: TreeNode
  selectedFile: string | null
  expandedDirs: Set<string>
  depth: number
}>()

const emit = defineEmits<{
  select: [filename: string]
  toggle: [dirPath: string]
}>()

function extColor(name: string): string {
  const ext = name.split('.').pop() || ''
  const map: Record<string, string> = {
    vue: 'text-green-600', ts: 'text-blue-600',
    js: 'text-yellow-600', css: 'text-pink-600',
  }
  return map[ext] || 'text-gray-600'
}

function handleSelect(): void {
  if (!props.node.isDir) {
    emit('select', props.node.path)
  } else {
    emit('toggle', props.node.path)
  }
}
</script>

<template>
  <!-- Directory node -->
  <template v-if="node.isDir">
    <div
      class="flex items-center gap-1 px-2 py-1 text-xs cursor-pointer hover:bg-gray-100 text-gray-600 font-medium select-none"
      :style="{ paddingLeft: `${depth * 12 + 8}px` }"
      @click="handleSelect"
    >
      <span class="text-[10px] w-3">{{ expandedDirs.has(node.path) ? '▼' : '▶' }}</span>
      <span class="text-xs">{{ expandedDirs.has(node.path) ? '📂' : '📁' }}</span>
      <span class="truncate">{{ node.name }}</span>
    </div>
    <template v-if="expandedDirs.has(node.path)">
      <FileTreeNode
        v-for="child in node.children"
        :key="child.path"
        :node="child"
        :selected-file="selectedFile"
        :expanded-dirs="expandedDirs"
        :depth="depth + 1"
        @select="emit('select', $event)"
        @toggle="emit('toggle', $event)"
      />
    </template>
  </template>

  <!-- File node -->
  <div
    v-else
    class="flex items-center gap-1.5 px-2 py-1 text-xs cursor-pointer hover:bg-gray-100 transition-colors"
    :class="{
      'bg-blue-50 text-blue-700 font-medium': selectedFile === node.path,
      'text-gray-700': selectedFile !== node.path,
    }"
    :style="{ paddingLeft: `${depth * 12 + 22}px` }"
    @click="handleSelect"
  >
    <span class="font-mono text-[10px]" :class="extColor(node.name)">●</span>
    <span class="truncate font-mono">{{ node.name }}</span>
  </div>
</template>
