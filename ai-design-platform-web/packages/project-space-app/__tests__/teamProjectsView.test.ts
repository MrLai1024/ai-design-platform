import { beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent } from 'vue';
import { flushPromises, mount } from '@vue/test-utils';
import { createMemoryHistory, createRouter } from 'vue-router';
import TeamProjectsView from '../src/views/TeamProjectsView.vue';
import { routes, ROUTE_NAMES } from '../src/router';
import { listTeamProjects } from '@ai-design/shared';
import type { Project } from '@ai-design/shared';

vi.mock('@ai-design/shared', () => ({
  listTeamProjects: vi.fn(),
}));

const sampleProject: Project = {
  id: 'p1',
  name: '团队演示项目',
  description: '团队项目简介',
  level: 'demo',
  teamId: 't1',
  createdBy: 'u1',
  createdAt: '2026-08-01',
};

/** Modal internals are covered by projectCreateModal.test.ts; the view test only checks the wiring */
const ProjectCreateModalStub = defineComponent({
  name: 'ProjectCreateModal',
  props: {
    open: { type: Boolean, default: false },
    teamId: { type: [String, null], default: null },
  },
  emits: ['cancel', 'created'],
  template: `
    <div v-if="open" data-testid="create-modal-stub">
      <button data-testid="stub-create" @click="$emit('created', { id: 'p1' })">stub create</button>
    </div>
  `,
});

async function mountView(teamId = 't1') {
  const router = createRouter({ history: createMemoryHistory(), routes });
  await router.push(`/teams/${teamId}`);
  await router.isReady();
  const wrapper = mount(TeamProjectsView, {
    global: { plugins: [router], stubs: { ProjectCreateModal: ProjectCreateModalStub } },
  });
  await flushPromises();
  return { wrapper, router };
}

beforeEach(() => {
  vi.mocked(listTeamProjects).mockReset();
});

describe('TeamProjectsView', () => {
  it('loads the team project list with the route teamId', async () => {
    vi.mocked(listTeamProjects).mockResolvedValue([sampleProject]);
    const { wrapper } = await mountView('team-42');

    expect(vi.mocked(listTeamProjects)).toHaveBeenCalledWith('team-42');
    const item = wrapper.find('[data-testid="project-item"]');
    expect(item.exists()).toBe(true);
    expect(item.text()).toContain('团队演示项目');
    expect(item.text()).toContain('演示级');
  });

  it('shows the empty state with a 新建项目 button', async () => {
    vi.mocked(listTeamProjects).mockResolvedValue([]);
    const { wrapper } = await mountView();

    const empty = wrapper.find('[data-testid="empty-state"]');
    expect(empty.exists()).toBe(true);
    expect(empty.text()).toContain('该团队暂无项目');
    expect(empty.find('button').text().replace(/\s/g, '')).toContain('新建项目');
  });

  it('opens the create modal with the teamId attached and refreshes on created', async () => {
    vi.mocked(listTeamProjects)
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([sampleProject]);
    const { wrapper } = await mountView();

    await wrapper.find('[data-testid="create-team-project-button"]').trigger('click');
    expect(wrapper.find('[data-testid="create-modal-stub"]').exists()).toBe(true);
    expect(wrapper.findComponent(ProjectCreateModalStub).props('teamId')).toBe('t1');

    await wrapper.find('[data-testid="stub-create"]').trigger('click');
    await flushPromises();

    expect(vi.mocked(listTeamProjects)).toHaveBeenCalledTimes(2);
    expect(wrapper.find('[data-testid="create-modal-stub"]').exists()).toBe(false);
    expect(wrapper.findAll('[data-testid="project-item"]')).toHaveLength(1);
  });

  it('navigates to the project detail with the team source query', async () => {
    vi.mocked(listTeamProjects).mockResolvedValue([sampleProject]);
    const { wrapper, router } = await mountView('team-42');

    await wrapper.find('[data-testid="project-item"]').trigger('click');
    await flushPromises();

    expect(router.currentRoute.value.name).toBe(ROUTE_NAMES.PROJECT_DETAIL);
    expect(router.currentRoute.value.params.id).toBe('p1');
    expect(router.currentRoute.value.query).toEqual({ from: 'team', teamId: 'team-42' });
  });

  it('reloads the list when navigating between teams', async () => {
    vi.mocked(listTeamProjects).mockResolvedValue([]);
    const { wrapper, router } = await mountView('t1');
    expect(vi.mocked(listTeamProjects)).toHaveBeenCalledWith('t1');

    await router.push('/teams/t2');
    await flushPromises();
    expect(vi.mocked(listTeamProjects)).toHaveBeenLastCalledWith('t2');
    expect(wrapper.find('[data-testid="empty-state"]').exists()).toBe(true);
  });
});
