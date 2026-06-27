<template>
  <div class="flex flex-col items-center justify-center h-full text-gray-400 select-none">
    <div class="text-6xl mb-4">💬</div>
    <p class="text-lg font-medium text-gray-300 mb-2">{{ title }}</p>
    <p class="text-sm text-gray-500">{{ subtitle }}</p>
  </div>
</template>

<script setup lang="ts">
withDefaults(defineProps<{
  title?: string;
  subtitle?: string;
}>(), {
  title: '开始一段新的 AI 对话',
  subtitle: '选择一个对话或点击新建',
});
</script>
