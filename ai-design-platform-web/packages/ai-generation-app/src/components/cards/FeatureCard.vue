<template>
  <div class="bg-white rounded-lg border p-4">
    <h3 class="text-base font-medium mb-3">🗂️ 功能模块</h3>
    <div class="space-y-2 mb-4">
      <div v-for="feat in features" :key="feat.id" class="border rounded p-2">
        <div class="flex items-center justify-between">
          <span class="text-sm font-medium">{{ feat.name }}</span>
          <span class="text-xs px-1.5 py-0.5 rounded" :class="{
            'bg-red-100 text-red-700': feat.priority === 'must',
            'bg-yellow-100 text-yellow-700': feat.priority === 'should',
            'bg-gray-100 text-gray-500': feat.priority === 'nice',
          }">{{ { must: '必须', should: '应该', nice: '锦上添花' }[feat.priority] }}</span>
        </div>
        <p class="text-xs text-gray-500 mt-1">{{ feat.description }}</p>
        <div class="mt-1 bg-gray-100 rounded-full h-1.5">
          <div class="bg-blue-500 rounded-full h-1.5" :style="{ width: feat.completeness + '%' }" />
        </div>
        <span class="text-xs text-gray-400">{{ feat.completeness }}%</span>
        <button v-if="feat.completeness < 80" class="ml-2 text-xs text-blue-500" @click="emit('supplement', feat.id)">补充</button>
      </div>
    </div>
    <button class="text-sm text-blue-500" @click="emit('addFeature')">+ 添加功能模块</button>

    <h3 class="text-base font-medium mt-4 mb-2">🗺️ 页面结构</h3>
    <div class="pl-2 border-l-2 border-gray-200">
      <div v-for="page in pages" :key="page.id" class="text-sm py-0.5" :class="{ 'ml-4': page.parent_id }">
        📄 {{ page.name }} <span class="text-xs text-gray-400">({{ page.page_type }})</span>
      </div>
    </div>
    <button class="text-sm text-blue-500 mt-1" @click="emit('addPage')">+ 添加页面</button>

    <div class="flex justify-between mt-4 pt-3 border-t">
      <button class="text-sm text-gray-500">✏️ 编辑</button>
      <button class="px-3 py-1 bg-blue-500 text-white text-sm rounded" @click="emit('confirm')">确认进入 →</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { FeatureModule, PageNode } from '@/types/requirements'
defineProps<{ features: FeatureModule[]; pages: PageNode[] }>()
const emit = defineEmits<{
  'supplement': [featureId: string]; 'addFeature': []; 'addPage': []; 'confirm': []
}>()
</script>
