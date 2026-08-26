<template>
  <a-layout class="app-layout">
    <a-layout-sider
      :width="200"
      theme="light"
      class="app-sider"
    >
      <a-menu
        :selected-keys="[activeMenuKey]"
        mode="inline"
        @click="onMenuClick"
      >
        <a-menu-item
          v-for="item in SIDE_MENU_ITEMS"
          :key="item.key"
        >
          {{ item.label }}
        </a-menu-item>
      </a-menu>
    </a-layout-sider>
    <a-layout>
      <a-layout-header class="app-header">
        <a-breadcrumb>
          <a-breadcrumb-item
            v-for="(item, index) in crumbs"
            :key="index"
          >
            <a
              v-if="item.path"
              @click.prevent="onCrumbClick(item)"
            >{{ item.label }}</a>
            <span v-else>{{ item.label }}</span>
          </a-breadcrumb-item>
        </a-breadcrumb>
      </a-layout-header>
      <a-layout-content class="app-content">
        <slot />
      </a-layout-content>
    </a-layout>
  </a-layout>
</template>

<script setup lang="ts">
import { computed, reactive, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import type { MenuInfo } from 'ant-design-vue/es/menu/src/interface';
import { getProject, listTeams } from '@ai-design/shared';
import { buildBreadcrumb, type BreadcrumbItem } from '../router/breadcrumb';
import { PATHS, ROUTE_NAMES } from '../router';
import { SIDE_MENU_ITEMS } from './menu';

const route = useRoute();
const router = useRouter();

/** Names resolved for the current route, fed into the breadcrumb builder */
const names = reactive({ teamName: '', projectName: '' });

/**
 * Resolve team/project names for breadcrumb display:
 * - teams/:teamId    → team name from listTeams (no dedicated team detail API)
 * - projects/:id     → project name from getProject; team-sourced details
 *                      additionally resolve the team name from listTeams
 * Failures are swallowed — the builder falls back to placeholder labels.
 */
let resolveSeq = 0;
async function resolveNames(): Promise<void> {
  const seq = ++resolveSeq;
  const name = route.name;

  if (name === ROUTE_NAMES.TEAM_PROJECTS) {
    const teamId = String(route.params.teamId ?? '');
    try {
      const teams = await listTeams();
      if (seq !== resolveSeq) return;
      names.teamName = teams.find((team) => team.id === teamId)?.name ?? '';
    } catch {
      if (seq !== resolveSeq) return;
      names.teamName = '';
    }
    names.projectName = '';
    return;
  }

  if (name === ROUTE_NAMES.PROJECT_DETAIL) {
    const projectId = String(route.params.id ?? '');
    try {
      const project = await getProject(projectId);
      if (seq !== resolveSeq) return;
      names.projectName = project.name;
    } catch {
      if (seq !== resolveSeq) return;
      names.projectName = '';
    }
    const teamId = typeof route.query.teamId === 'string' ? route.query.teamId : '';
    if (route.query.from === 'team' && teamId) {
      try {
        const teams = await listTeams();
        if (seq !== resolveSeq) return;
        names.teamName = teams.find((team) => team.id === teamId)?.name ?? '';
      } catch {
        if (seq !== resolveSeq) return;
        names.teamName = '';
      }
    } else {
      names.teamName = '';
    }
    return;
  }

  names.teamName = '';
  names.projectName = '';
}

watch(
  () => [route.name, route.params, route.query],
  () => {
    void resolveNames();
  },
  { immediate: true },
);

const crumbs = computed(() =>
  buildBreadcrumb(
    route,
    route.params as Record<string, string>,
    route.query as Record<string, unknown>,
    { teamName: names.teamName || undefined, projectName: names.projectName || undefined },
  ),
);

/** Side menu selection follows the route; team detail pages keep 团队项目 selected */
const activeMenuKey = computed(() => {
  if (route.name === ROUTE_NAMES.TEAMS || route.name === ROUTE_NAMES.TEAM_PROJECTS) {
    return PATHS.TEAMS;
  }
  if (route.name === ROUTE_NAMES.PROJECT_DETAIL && route.query.from === 'team') {
    return PATHS.TEAMS;
  }
  return PATHS.PERSONAL;
});

function onMenuClick(info: MenuInfo): void {
  void router.push(String(info.key));
}

/** 首页 goes back to the base app via full page load; other levels stay in-app */
function onCrumbClick(item: BreadcrumbItem): void {
  if (!item.path) return;
  if (item.external) {
    window.location.href = item.path;
  } else {
    void router.push(item.path);
  }
}
</script>
