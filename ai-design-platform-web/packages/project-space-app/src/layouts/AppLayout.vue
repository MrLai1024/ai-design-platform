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
            <span
              v-else
              class="crumb-current"
            >{{ item.label }}</span>
          </a-breadcrumb-item>
        </a-breadcrumb>
      </a-layout-header>
      <a-layout-content class="app-content">
        <slot />
      </a-layout-content>
    </a-layout>
  </a-layout>
</template>

<style scoped>
.app-layout {
  min-height: 100%;
  /* 灰色画布(用户定色 rgb(134,134,134));!important 防 qiankun 前缀竞态被 antd 默认 #f5f5f5 覆盖 */
  background: rgb(134, 134, 134) !important;
}

/* 侧栏:白底 + 右侧描边 + 投影,在深灰画布上浮起 */
.app-sider.ant-layout-sider {
  background: #fff;
  border-right: 1px solid #e0e0e0;
  box-shadow: 1px 0 8px rgba(0, 0, 0, 0.15);
}

/* antd 的 .ant-layout-header 默认样式(暗蓝底/64px 高)经 cssinjs 注入且源顺序靠后,
   仅用 .app-header(0,1,0)会同特异性落败;组合选择器抬高特异性以稳定覆盖 */
.app-header.ant-layout-header {
  height: 48px;
  line-height: 48px;
  padding: 0 24px;
  background: #fff;
  border-bottom: 1px solid #e0e0e0;
  box-shadow: 0 1px 8px rgba(0, 0, 0, 0.15);
}

/* 内容区:白卡片(圆角+描边+阴影),浮在灰色画布上,与头部/侧栏界限分明 */
.app-content.ant-layout-content {
  margin: 16px;
  padding: 4px 0;
  background: #fff;
  border: 1px solid #e6e6e6;
  border-radius: 8px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.16);
}

/* 面包屑当前项高亮(主题蓝 + 加粗);组合选择器抬高特异性以稳定覆盖 antd last-child 样式 */
.app-header :deep(.ant-breadcrumb) .crumb-current {
  color: #1677ff;
  font-weight: 600;
}
</style>

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
