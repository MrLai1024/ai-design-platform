<template>
  <div class="bg-white rounded-lg border p-4">
    <h3 class="text-base font-medium mb-3">📋 项目愿景</h3>
    <div class="space-y-3">
      <div>
        <label class="text-xs text-gray-500">项目名称</label>
        <input :value="vision?.project_name ?? ''" class="w-full border rounded px-2 py-1 text-sm mt-1"
          @input="emit('update:vision', { ...vision!, project_name: ($event.target as HTMLInputElement).value })" />
      </div>
      <div>
        <label class="text-xs text-gray-500">👥 目标用户</label>
        <div v-for="(user, i) in vision?.target_users ?? []" :key="i" class="flex gap-1 mt-1">
          <input :value="user.role" class="flex-1 border rounded px-2 py-1 text-sm" placeholder="角色"
            @input="updateUser(i, 'role', ($event.target as HTMLInputElement).value)" />
          <input :value="user.description" class="flex-1 border rounded px-2 py-1 text-sm" placeholder="描述"
            @input="updateUser(i, 'description', ($event.target as HTMLInputElement).value)" />
          <button class="text-red-400 text-sm" @click="removeUser(i)">✕</button>
        </div>
        <button class="text-blue-500 text-xs mt-1" @click="addUser">+ 添加</button>
      </div>
      <div>
        <label class="text-xs text-gray-500">🎯 核心问题</label>
        <textarea :value="vision?.core_problem ?? ''" class="w-full border rounded px-2 py-1 text-sm mt-1" rows="2"
          @input="emit('update:vision', { ...vision!, core_problem: ($event.target as HTMLTextAreaElement).value })" />
      </div>
      <div>
        <label class="text-xs text-gray-500">✅ 成功标准</label>
        <div v-for="(c, i) in vision?.success_criteria ?? []" :key="i" class="flex gap-1 mt-1">
          <input :value="c" class="flex-1 border rounded px-2 py-1 text-sm"
            @input="updateCriterion(i, ($event.target as HTMLInputElement).value)" />
          <button class="text-red-400 text-sm" @click="removeCriterion(i)">✕</button>
        </div>
        <button class="text-blue-500 text-xs mt-1" @click="addCriterion">+ 添加</button>
      </div>
      <div>
        <label class="text-xs text-gray-500">📐 范围说明</label>
        <textarea :value="vision?.scope_note ?? ''" class="w-full border rounded px-2 py-1 text-sm mt-1" rows="2"
          @input="emit('update:vision', { ...vision!, scope_note: ($event.target as HTMLTextAreaElement).value })" />
      </div>
    </div>
    <div class="flex justify-between mt-4 pt-3 border-t">
      <button class="text-sm text-gray-500 hover:text-gray-700">✏️ 编辑</button>
      <button class="px-3 py-1 bg-blue-500 text-white text-sm rounded hover:bg-blue-600" @click="emit('confirm')">确认进入 →</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { VisionData } from '@/types/requirements'

const props = defineProps<{ vision: VisionData | null }>()
const emit = defineEmits<{ 'update:vision': [data: VisionData]; 'confirm': [] }>()

function updateUser(index: number, field: string, value: string) {
  if (!props.vision) return
  const users = [...props.vision.target_users]
  users[index] = { ...users[index], [field]: value }
  emit('update:vision', { ...props.vision, target_users: users })
}
function addUser() {
  if (!props.vision) return
  emit('update:vision', { ...props.vision, target_users: [...props.vision.target_users, { role: '', description: '' }] })
}
function removeUser(index: number) {
  if (!props.vision) return
  emit('update:vision', { ...props.vision, target_users: props.vision.target_users.filter((_, i) => i !== index) })
}
function updateCriterion(index: number, value: string) {
  if (!props.vision) return
  const criteria = [...props.vision.success_criteria]
  criteria[index] = value
  emit('update:vision', { ...props.vision, success_criteria: criteria })
}
function addCriterion() {
  if (!props.vision) return
  emit('update:vision', { ...props.vision, success_criteria: [...props.vision.success_criteria, ''] })
}
function removeCriterion(index: number) {
  if (!props.vision) return
  emit('update:vision', { ...props.vision, success_criteria: props.vision.success_criteria.filter((_, i) => i !== index) })
}
</script>
