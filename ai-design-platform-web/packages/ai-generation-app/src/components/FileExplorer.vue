<!-- src/components/FileExplorer.vue -->
<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useGenerationStore } from '@/stores/generation'
import FileTreeNode from './FileTreeNode.vue'

const store = useGenerationStore()
const selectedFile = ref<string | null>(null)
const expandedDirs = ref<Set<string>>(new Set())

interface TreeNode {
  name: string
  path: string
  isDir: boolean
  children: TreeNode[]
}

// Build recursive file tree from flat file list
const fileTree = computed<TreeNode[]>(() => {
  const root: TreeNode = { name: '', path: '', isDir: true, children: [] }

  for (const entry of store.fileList) {
    const parts = entry.filename.split('/')
    let current = root
    for (let i = 0; i < parts.length; i++) {
      const isLast = i === parts.length - 1
      const fullPath = parts.slice(0, i + 1).join('/')
      let child = current.children.find(c => c.name === parts[i]!)
      if (!child) {
        child = {
          name: parts[i]!,
          path: isLast ? entry.filename : fullPath,
          isDir: !isLast,
          children: [],
        }
        current.children.push(child)
      }
      current = child
    }
  }

  // Auto-expand all dirs when files first appear
  if (root.children.length > 0 && expandedDirs.value.size === 0) {
    const dirs = new Set<string>()
    function collectDirs(node: TreeNode) {
      if (node.isDir && node.path) dirs.add(node.path)
      for (const c of node.children) collectDirs(c)
    }
    collectDirs(root)
    expandedDirs.value = dirs
  }

  return root.children
})

const currentFile = computed(() => {
  if (!selectedFile.value) return null
  const entry = store.files.get(selectedFile.value)
  if (entry) {
    // If there's streaming content for same file, show the latest
    if (streamingContent.value) {
      return { ...entry, content: streamingContent.value }
    }
    return entry
  }
  // File is being streamed — show from generatedFiles or streamingContent
  const content = streamingContent.value || store.generatedFiles[selectedFile.value] || ''
  if (content) {
    return {
      filename: selectedFile.value,
      content,
      language: selectedFile.value.endsWith('.vue') ? 'vue' as const
        : selectedFile.value.endsWith('.ts') ? 'typescript' as const
        : 'javascript' as const,
      isDirty: false,
      source: 'ai' as const,
    }
  }
  return null
})

function selectFile(filename: string): void {
  selectedFile.value = filename
  store.setActiveFile(filename)
}

function toggleDir(dirPath: string): void {
  if (expandedDirs.value.has(dirPath)) {
    expandedDirs.value.delete(dirPath)
  } else {
    expandedDirs.value.add(dirPath)
  }
}

// Auto-select first file when files appear
watch(
  () => store.fileList.length,
  (len) => {
    if (len > 0 && !selectedFile.value) {
      selectedFile.value = store.fileList[0]!.filename
      store.setActiveFile(store.fileList[0]!.filename)
    }
  },
  { immediate: true },
)

// Streaming content ref — updated reactively to drive real-time code display
const streamingContent = ref<string>('')

// Auto-focus new file + track streaming content
watch(
  () => store.currentGeneratingFile,
  (path) => {
    if (path) {
      selectedFile.value = path
      store.setActiveFile(path)
      const dir = path.includes('/') ? path.substring(0, path.lastIndexOf('/')) : ''
      if (dir) expandedDirs.value.add(dir)
    }
  },
)

// Watch generatedFiles for the selected file's streaming content
watch(
  () => selectedFile.value ? store.generatedFiles[selectedFile.value] : '',
  (content) => {
    streamingContent.value = content || ''
  },
)
</script>

<template>
  <div class="file-explorer flex h-full bg-white">
    <!-- 左侧文件树 -->
    <div class="w-[200px] min-w-[160px] border-r border-gray-200 overflow-y-auto bg-gray-50">
      <template v-for="node in fileTree" :key="node.path">
        <FileTreeNode
          :node="node"
          :selected-file="selectedFile"
          :expanded-dirs="expandedDirs"
          :depth="0"
          @select="selectFile"
          @toggle="toggleDir"
        />
      </template>

      <div v-if="store.fileList.length === 0" class="p-4 text-center text-gray-400 text-xs">
        暂无文件 — 等待代码生成
      </div>
    </div>

    <!-- 右侧代码查看器 -->
    <div class="flex-1 overflow-y-auto bg-[#1e1e2e]">
      <div v-if="currentFile" class="p-4">
        <div class="text-xs text-gray-400 mb-2 font-mono">
          {{ currentFile.filename }}
          <span
            class="ml-2"
            :class="{
              'text-green-400': currentFile.language === 'vue',
              'text-blue-400': currentFile.language === 'typescript',
              'text-yellow-400': currentFile.language === 'javascript',
              'text-pink-400': currentFile.language === 'css',
            }"
          >
            ({{ currentFile.language }})
          </span>
        </div>
        <pre class="text-sm text-gray-200 font-mono whitespace-pre-wrap"><code>{{ currentFile.content }}</code></pre>
      </div>
      <div v-else class="p-4 text-center text-gray-500 text-sm">
        选择文件查看代码
      </div>
    </div>
  </div>
</template>
