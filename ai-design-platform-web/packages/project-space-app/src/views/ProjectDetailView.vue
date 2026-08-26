<template>
  <div class="page">
    <a-tabs v-model:active-key="activeTab">
      <a-tab-pane
        key="issues"
        tab="Issue"
      >
        <a-empty
          description="Issue 功能开发中,敬请期待"
          data-testid="issues-placeholder"
        />
      </a-tab-pane>
      <a-tab-pane
        key="repo"
        tab="代码仓"
      >
        <a-empty
          description="代码仓功能开发中,敬请期待"
          data-testid="repo-placeholder"
        />
      </a-tab-pane>
    </a-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue';

const activeTab = ref('issues');
</script>
