<template>
  <a-modal
    :open="open"
    title="加入团队"
    :footer="null"
    width="480"
    :get-container="getAppContainer"
    @cancel="emit('cancel')"
  >
    <!-- no :loading on the search button: antd blocks clicks/Enter while loading,
         which would trap the user in a slow first search. The searchSeq guard in
         doSearch keeps out-of-order responses correct instead. -->
    <a-input-search
      v-model:value="keyword"
      placeholder="输入团队名称关键字搜索"
      enter-button="搜索"
      data-testid="team-search-input"
      @search="doSearch"
    />
    <a-spin
      :spinning="searching"
      class="join-results"
    >
      <div
        v-if="joinError"
        class="join-error"
        data-testid="join-error"
      >
        {{ joinError }}
      </div>
      <a-empty
        v-if="!joinError && searched && results.length === 0"
        description="未找到匹配的团队"
        data-testid="join-empty"
      />
      <a-list
        v-if="results.length > 0"
        :data-source="results"
        size="small"
      >
        <template #renderItem="{ item }">
          <a-list-item
            class="join-result-item"
            data-testid="join-result-item"
          >
            <div class="join-result-info">
              <div class="join-result-name">
                {{ item.name }}
              </div>
              <div
                v-if="item.description"
                class="join-result-desc"
              >
                {{ item.description }}
              </div>
            </div>
            <a-button
              type="primary"
              size="small"
              :loading="joiningId === item.id"
              @click="join(item)"
            >
              加入
            </a-button>
          </a-list-item>
        </template>
      </a-list>
    </a-spin>
  </a-modal>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue';
import { joinTeam, searchTeams } from '@ai-design/shared';
import type { Team } from '@ai-design/shared';
import { getAppRoot } from '../portal-root';

const props = withDefaults(defineProps<{ open?: boolean }>(), { open: false });

const emit = defineEmits<{
  cancel: [];
  joined: [team: Team];
}>();

const keyword = ref('');

// Keep the modal inside the qiankun wrapper (see portal-root.ts) so qiankun's
// scopedCSS-prefixed rules still match teleported overlay content.
function getAppContainer(): HTMLElement {
  return getAppRoot();
}
const results = ref<Team[]>([]);
const searched = ref(false);
const searching = ref(false);
const joiningId = ref<string | null>(null);
const joinError = ref('');
/** Teams joined during this modal session — filtered out of later searches */
const joinedIds = new Set<string>();

watch(
  () => props.open,
  (open) => {
    if (open) {
      keyword.value = '';
      results.value = [];
      searched.value = false;
      searching.value = false;
      joiningId.value = null;
      joinError.value = '';
      joinedIds.clear();
      // invalidate any in-flight search from a previous session
      searchSeq += 1;
    }
  },
);

/**
 * Monotonic token guarding against out-of-order search responses: only the
 * latest search may write results/error/searching state — stale responses
 * (success or failure) are discarded.
 */
let searchSeq = 0;

async function doSearch(): Promise<void> {
  const kw = keyword.value.trim();
  if (!kw) return;
  const seq = ++searchSeq;
  searching.value = true;
  joinError.value = '';
  try {
    const teams = await searchTeams(kw);
    if (seq !== searchSeq) return;
    results.value = teams.filter((team) => !joinedIds.has(team.id));
    searched.value = true;
  } catch {
    if (seq !== searchSeq) return;
    joinError.value = '搜索失败,请稍后重试';
  } finally {
    if (seq === searchSeq) {
      searching.value = false;
    }
  }
}

/** HTTP 409 = already a member (duplicate join) */
function isConflict(error: unknown): boolean {
  if (typeof error !== 'object' || error === null || !('response' in error)) {
    return false;
  }
  const status = (error as { response?: { status?: unknown } }).response?.status;
  return status === 409;
}

/**
 * 服务端错误提示:响应拦截器把信封的 msg 写入 error.message 并附上 apiCode 业务码。
 * 有 apiCode 标记才视为服务端 msg,避免把 axios 的网络错误文案("Network Error")展示给用户。
 */
function serverMessage(error: unknown): string {
  if (typeof error !== 'object' || error === null) return '';
  const e = error as { apiCode?: unknown; message?: unknown };
  return typeof e.apiCode === 'number' && typeof e.message === 'string' ? e.message : '';
}

async function join(team: Team): Promise<void> {
  joiningId.value = team.id;
  joinError.value = '';
  try {
    await joinTeam(team.id);
    joinedIds.add(team.id);
    results.value = results.value.filter((item) => item.id !== team.id);
    emit('joined', team);
  } catch (error) {
    // 服务端 msg 优先(409 时后端返回"已加入该团队");无服务端提示时回退本地文案
    joinError.value =
      serverMessage(error) ||
      (isConflict(error) ? '你已加入该团队,无需重复加入' : '加入失败,请稍后重试');
  } finally {
    joiningId.value = null;
  }
}
</script>
