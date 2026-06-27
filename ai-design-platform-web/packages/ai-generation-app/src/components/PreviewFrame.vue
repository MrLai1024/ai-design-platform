<!-- src/components/PreviewFrame.vue -->
<script setup lang="ts">
import { usePreviewRenderer } from '@/composables/usePreviewRenderer'
import { useMultiCompiler } from '@/composables/useMultiCompiler'

const { iframeRef, iframeReady, errorMessage, refresh } = usePreviewRenderer()
const { isCompiling } = useMultiCompiler()
</script>

<template>
  <div class="preview-frame flex flex-col h-full bg-white">
    <div class="px-4 py-2 border-b border-gray-200 bg-gray-50 flex items-center justify-between">
      <h2 class="text-sm font-semibold text-gray-700">实时预览</h2>
      <div class="flex items-center gap-2">
        <span v-if="isCompiling" class="text-xs px-2 py-0.5 rounded-full bg-yellow-100 text-yellow-700">
          编译中...
        </span>
        <span v-else-if="iframeReady" class="text-xs px-2 py-0.5 rounded-full bg-green-100 text-green-700">
          已就绪
        </span>
        <span v-else class="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-500">
          等待中
        </span>
        <button
          @click="refresh"
          class="text-xs text-blue-600 hover:text-blue-800 px-2 py-0.5 rounded hover:bg-blue-50 transition-colors"
          title="刷新预览"
        >
          ↻ 刷新
        </button>
      </div>
    </div>

    <div class="flex-1 relative">
      <div v-if="!iframeReady" class="absolute inset-0 flex items-center justify-center text-gray-400 text-sm">
        <div class="text-center">
          <div v-if="isCompiling" class="animate-pulse">编译中...</div>
          <div v-else>输入描述开始生成组件</div>
        </div>
      </div>
      <iframe
        ref="iframeRef"
        sandbox="allow-scripts"
        class="w-full h-full border-none"
        title="组件预览"
      />
    </div>

    <div
      v-if="errorMessage"
      class="px-4 py-3 bg-red-50 border-t border-red-200"
    >
      <pre class="text-xs text-red-600 whitespace-pre-wrap font-mono">{{ errorMessage }}</pre>
    </div>
  </div>
</template>
