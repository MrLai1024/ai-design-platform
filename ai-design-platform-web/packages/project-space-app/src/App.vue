<template>
  <div class="project-space-app">
    <AppLayout>
      <router-view />
    </AppLayout>
  </div>
</template>

<script setup lang="ts">
import AppLayout from './layouts/AppLayout.vue';
</script>
