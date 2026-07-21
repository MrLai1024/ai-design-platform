<template>
  <div class="bg-white rounded-lg border p-4">
    <h3 class="text-base font-medium mb-3">📝 页面详情</h3>
    <div class="mb-4">
      <select class="border rounded px-2 py-1 text-sm w-full" @change="selectedPageId = ($event.target as HTMLSelectElement).value">
        <option value="">选择页面...</option>
        <option v-for="p in pages" :key="p.id" :value="p.id">{{ p.name }}</option>
      </select>
    </div>
    <div v-if="selectedPageId && pageDetail" class="space-y-3">
      <div>
        <label class="text-xs text-gray-500">展示字段</label>
        <div v-for="(f, i) in pageDetail.display_fields" :key="i" class="flex gap-1 mt-1 text-sm">
          <span class="w-24">{{ f.name }}</span>
          <span class="text-gray-400">{{ f.type }}</span>
          <span v-if="f.required" class="text-red-400">*</span>
        </div>
      </div>
      <div>
        <label class="text-xs text-gray-500">操作按钮</label>
        <div class="flex gap-1 mt-1 flex-wrap">
          <span v-for="(a, i) in pageDetail.action_buttons" :key="i" class="px-2 py-0.5 bg-gray-100 rounded text-sm">{{ a.label }}</span>
        </div>
      </div>
      <div>
        <label class="text-xs text-gray-500">关联数据</label>
        <div class="text-sm text-gray-600">{{ pageDetail.related_data.join(' · ') || '无' }}</div>
      </div>
    </div>

    <h3 class="text-base font-medium mt-4 mb-2">🔧 技术约束</h3>
    <div class="grid grid-cols-2 gap-2 text-sm">
      <div><label class="text-xs text-gray-500">前端框架</label><div class="border rounded px-2 py-1">{{ techConstraints?.framework || '待确认' }}</div></div>
      <div><label class="text-xs text-gray-500">组件库</label><div class="border rounded px-2 py-1">{{ techConstraints?.component_lib || '待确认' }}</div></div>
      <div><label class="text-xs text-gray-500">数据来源</label><div class="border rounded px-2 py-1">{{ techConstraints?.data_source || '待确认' }}</div></div>
    </div>

    <h3 class="text-base font-medium mt-4 mb-2">📊 数据实体</h3>
    <div v-for="e in dataEntities" :key="e.name" class="border rounded p-2 mb-1 text-sm">
      <span class="font-medium">{{ e.name }}:</span>
      <span class="text-gray-500">{{ e.fields.map(f => f.name).join(' / ') }}</span>
    </div>

    <div class="flex justify-between mt-4 pt-3 border-t">
      <button class="text-sm text-gray-500">✏️ 编辑</button>
      <button class="px-3 py-1 bg-green-500 text-white text-sm rounded" @click="emit('generate')">生成需求文档 →</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import type { PageNode, PageDetail, TechConstraints, DataEntity } from '@/types/requirements'

const props = defineProps<{
  pages: PageNode[]; pageDetails: Record<string, PageDetail>
  techConstraints: TechConstraints; dataEntities: DataEntity[]
}>()
const emit = defineEmits<{ 'generate': [] }>()
const selectedPageId = ref('')
const pageDetail = computed(() => selectedPageId.value ? (props.pageDetails[selectedPageId.value] ?? null) : null)
</script>
