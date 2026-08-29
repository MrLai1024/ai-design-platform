<template>
  <a-tag
    :color="color"
    class="project-level-tag"
    data-testid="level-tag"
  >
    {{ label }}
  </a-tag>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import type { ProjectLevel } from '@ai-design/shared';

const props = defineProps<{ level: ProjectLevel }>();

const label = computed(() => (props.level === 'production' ? '生产级' : '演示级'));
const color = computed(() => (props.level === 'production' ? 'gold' : 'blue'));
</script>
