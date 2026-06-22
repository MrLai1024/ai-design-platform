<template>
  <div :id="containerId" class="sub-app-container min-h-full" />
</template>

<script setup lang="ts">
defineProps<{
  containerId: string;
}>();
</script>

<style scoped>
.sub-app-container {
  min-height: 400px;
}
</style>
