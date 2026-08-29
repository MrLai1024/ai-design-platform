<template>
  <div class="page detail-page">
    <a-menu
      v-model:selected-keys="selectedKeys"
      mode="inline"
      class="detail-menu"
      data-testid="detail-menu"
    >
      <a-menu-item key="issues">
        Issue
      </a-menu-item>
      <a-menu-item key="repo">
        代码仓
      </a-menu-item>
    </a-menu>
    <div class="detail-panel">
      <a-empty
        v-if="activeKey === 'issues'"
        description="Issue 功能开发中,敬请期待"
        data-testid="issues-placeholder"
      />
      <a-empty
        v-else
        description="代码仓功能开发中,敬请期待"
        data-testid="repo-placeholder"
      />
    </div>
  </div>
</template>

<style scoped>
/* 项目详情页:左侧竖排菜单 + 右侧内容区 */
.detail-page {
  display: flex;
  align-items: flex-start;
}

.detail-menu.ant-menu {
  width: 160px;
  flex-shrink: 0;
  border-right: 1px solid #f0f0f0;
}

.detail-panel {
  flex: 1;
  padding: 4px 0 0 24px;
  min-height: 240px;
}
</style>

<script setup lang="ts">
import { computed, ref } from 'vue';

const selectedKeys = ref<string[]>(['issues']);
const activeKey = computed(() => selectedKeys.value[0] ?? 'issues');
</script>
