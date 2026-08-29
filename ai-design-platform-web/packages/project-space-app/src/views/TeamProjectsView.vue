<template>
  <div class="page">
    <div class="page-toolbar">
      <h2 class="page-title">
        团队项目
      </h2>
      <a-button
        type="primary"
        data-testid="create-team-project-button"
        @click="createModalOpen = true"
      >
        新建项目
      </a-button>
    </div>
    <a-spin :spinning="loading">
      <div
        v-if="error"
        class="page-error"
      >
        <a-alert
          type="error"
          :message="error"
          show-icon
        />
        <a-button
          data-testid="retry-button"
          @click="load"
        >
          重试
        </a-button>
      </div>
      <a-empty
        v-else-if="!loading && projects.length === 0"
        description="该团队暂无项目"
        data-testid="empty-state"
      >
        <a-button
          type="primary"
          @click="createModalOpen = true"
        >
          新建项目
        </a-button>
      </a-empty>
      <a-list
        v-else
        :data-source="projects"
        data-testid="project-list"
      >
        <template #renderItem="{ item }">
          <a-list-item
            class="clickable-item"
            data-testid="project-item"
            @click="goDetail(item)"
          >
            <a-list-item-meta>
              <template #title>
                <span class="item-name">{{ item.name }}</span>
                <ProjectLevelTag :level="item.level" />
              </template>
              <template #description>
                <span class="item-desc">{{ item.description || '暂无简介' }}</span>
              </template>
            </a-list-item-meta>
          </a-list-item>
        </template>
      </a-list>
    </a-spin>
    <ProjectCreateModal
      :open="createModalOpen"
      :team-id="teamId"
      @cancel="createModalOpen = false"
      @created="onProjectCreated"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { listTeamProjects } from '@ai-design/shared';
import type { Project } from '@ai-design/shared';
import ProjectCreateModal from '../components/ProjectCreateModal.vue';
import ProjectLevelTag from '../components/ProjectLevelTag.vue';
import { PATHS } from '../router/paths';

const route = useRoute();
const router = useRouter();
const teamId = computed(() => String(route.params.teamId ?? ''));

const projects = ref<Project[]>([]);
const loading = ref(false);
const error = ref('');
const createModalOpen = ref(false);

async function load(): Promise<void> {
  loading.value = true;
  error.value = '';
  try {
    projects.value = await listTeamProjects(teamId.value);
  } catch {
    error.value = '项目列表加载失败,请稍后重试';
  } finally {
    loading.value = false;
  }
}

function onProjectCreated(): void {
  createModalOpen.value = false;
  void load();
}

function goDetail(project: Project): void {
  void router.push({
    path: PATHS.projectDetail(project.id),
    query: { from: 'team', teamId: teamId.value },
  });
}

// immediate: loads on mount and re-loads when navigating between teams
watch(
  teamId,
  () => {
    void load();
  },
  { immediate: true },
);
</script>
