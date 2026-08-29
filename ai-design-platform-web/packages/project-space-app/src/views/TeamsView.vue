<template>
  <div class="page">
    <div class="page-toolbar">
      <h2 class="page-title">
        我的团队
      </h2>
      <div class="toolbar-actions">
        <a-button
          data-testid="join-team-button"
          @click="joinModalOpen = true"
        >
          加入团队
        </a-button>
        <a-button
          type="primary"
          data-testid="create-team-button"
          @click="createModalOpen = true"
        >
          创建团队
        </a-button>
      </div>
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
        v-else-if="!loading && teams.length === 0"
        description="还没有加入任何团队"
        data-testid="teams-empty"
      >
      </a-empty>
      <a-list
        v-else
        :data-source="teams"
        data-testid="team-list"
      >
        <template #renderItem="{ item }">
          <a-list-item
            class="clickable-item"
            data-testid="team-item"
            @click="goTeamProjects(item)"
          >
            <a-list-item-meta>
              <template #title>
                <span class="item-name">{{ item.name }}</span>
              </template>
              <template #description>
                <span class="item-desc">{{ item.description || '暂无简介' }}</span>
              </template>
            </a-list-item-meta>
          </a-list-item>
        </template>
      </a-list>
    </a-spin>
    <TeamCreateModal
      :open="createModalOpen"
      @cancel="createModalOpen = false"
      @created="onTeamCreated"
    />
    <TeamJoinModal
      :open="joinModalOpen"
      @cancel="joinModalOpen = false"
      @joined="onTeamJoined"
    />
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import { listTeams } from '@ai-design/shared';
import type { Team } from '@ai-design/shared';
import TeamCreateModal from '../components/TeamCreateModal.vue';
import TeamJoinModal from '../components/TeamJoinModal.vue';
import { PATHS } from '../router/paths';

const router = useRouter();
const teams = ref<Team[]>([]);
const loading = ref(false);
const error = ref('');
const createModalOpen = ref(false);
const joinModalOpen = ref(false);

async function load(): Promise<void> {
  loading.value = true;
  error.value = '';
  try {
    teams.value = await listTeams();
  } catch {
    error.value = '团队列表加载失败,请稍后重试';
  } finally {
    loading.value = false;
  }
}

function onTeamCreated(): void {
  createModalOpen.value = false;
  void load();
}

/** Keep the join modal open so the user can join more teams; refresh the list below */
function onTeamJoined(): void {
  void load();
}

function goTeamProjects(team: Team): void {
  void router.push(PATHS.teamProjects(team.id));
}

onMounted(() => {
  void load();
});
</script>
