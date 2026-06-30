<!-- src/components/StageOutput.vue -->
<script setup lang="ts">
import { ref } from 'vue'
import MarkdownRenderer from '@ai-design/shared/components/MarkdownRenderer.vue'

const props = defineProps<{
  title: string
  content: string | null
}>()

const emit = defineEmits<{
  'save': [content: string]
}>()

const isEditing = ref(false)
const editContent = ref('')

function startEdit(): void {
  editContent.value = props.content || ''
  isEditing.value = true
}

function saveEdit(): void {
  emit('save', editContent.value)
  isEditing.value = false
}

function cancelEdit(): void {
  isEditing.value = false
}
</script>

<template>
  <div class="stage-output flex flex-col h-full">
    <div class="px-4 py-2 border-b border-gray-200 bg-gray-50 flex items-center justify-between">
      <h3 class="text-sm font-semibold text-gray-700">{{ title }}</h3>
      <button
        v-if="!isEditing && content"
        class="text-xs px-2 py-1 rounded border border-gray-300 text-gray-600 hover:bg-gray-100 transition-colors"
        @click="startEdit"
      >
        ✏️ 编辑
      </button>
    </div>

    <div class="flex-1 overflow-y-auto p-4">
      <div v-if="!content && !isEditing" class="text-center text-gray-400 mt-8">
        <p>等待阶段完成...</p>
      </div>

      <!-- 查看模式 -->
      <MarkdownRenderer v-if="!isEditing && content" :content="content" />

      <!-- 编辑模式 -->
      <div v-if="isEditing" class="flex flex-col h-full gap-2">
        <textarea
          v-model="editContent"
          class="flex-1 w-full border border-gray-300 rounded-lg p-3 text-sm font-mono resize-none focus:outline-none focus:ring-2 focus:ring-blue-500"
          rows="15"
        />
        <div class="flex gap-2 justify-end">
          <button
            class="px-3 py-1.5 text-xs rounded border border-gray-300 text-gray-600 hover:bg-gray-100"
            @click="cancelEdit"
          >
            取消
          </button>
          <button
            class="px-3 py-1.5 text-xs rounded bg-blue-600 text-white hover:bg-blue-700"
            @click="saveEdit"
          >
            保存修改
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
