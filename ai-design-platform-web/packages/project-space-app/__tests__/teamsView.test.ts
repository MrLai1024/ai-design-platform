import { beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent } from 'vue';
import { flushPromises, mount } from '@vue/test-utils';
import { createMemoryHistory, createRouter } from 'vue-router';
import TeamsView from '../src/views/TeamsView.vue';
import { routes, ROUTE_NAMES } from '../src/router';
import { listTeams } from '@ai-design/shared';
import type { Team } from '@ai-design/shared';

vi.mock('@ai-design/shared', () => ({
  listTeams: vi.fn(),
}));

const sampleTeam: Team = {
  id: 't1',
  name: '星辰团队',
  description: '前端小组',
  ownerId: 'u1',
  createdAt: '2026-08-01',
};

/** Modal internals are covered by teamCreateModal/teamJoinModal tests; the view test only checks the wiring */
const TeamCreateModalStub = defineComponent({
  name: 'TeamCreateModal',
  props: { open: { type: Boolean, default: false } },
  emits: ['cancel', 'created'],
  template: `
    <div v-if="open" data-testid="create-team-modal-stub">
      <button data-testid="stub-create-team" @click="$emit('created', { id: 't1' })">stub create team</button>
    </div>
  `,
});

const TeamJoinModalStub = defineComponent({
  name: 'TeamJoinModal',
  props: { open: { type: Boolean, default: false } },
  emits: ['cancel', 'joined'],
  template: `
    <div v-if="open" data-testid="join-team-modal-stub">
      <button data-testid="stub-join-team" @click="$emit('joined', { id: 't1' })">stub join team</button>
    </div>
  `,
});

async function mountView() {
  const router = createRouter({ history: createMemoryHistory(), routes });
  await router.push('/teams');
  await router.isReady();
  const wrapper = mount(TeamsView, {
    global: {
      plugins: [router],
      stubs: { TeamCreateModal: TeamCreateModalStub, TeamJoinModal: TeamJoinModalStub },
    },
  });
  await flushPromises();
  return { wrapper, router };
}

beforeEach(() => {
  vi.mocked(listTeams).mockReset();
});

describe('TeamsView', () => {
  it('renders my teams list and navigates to the team projects page on click', async () => {
    vi.mocked(listTeams).mockResolvedValue([sampleTeam]);
    const { wrapper, router } = await mountView();

    const item = wrapper.find('[data-testid="team-item"]');
    expect(item.exists()).toBe(true);
    expect(item.text()).toContain('星辰团队');
    expect(item.text()).toContain('前端小组');

    await item.trigger('click');
    await flushPromises();
    expect(router.currentRoute.value.name).toBe(ROUTE_NAMES.TEAM_PROJECTS);
    expect(router.currentRoute.value.params.teamId).toBe('t1');
  });

  it('shows the empty state with 创建团队 and 加入团队 entries', async () => {
    vi.mocked(listTeams).mockResolvedValue([]);
    const { wrapper } = await mountView();

    const empty = wrapper.find('[data-testid="teams-empty"]');
    expect(empty.exists()).toBe(true);
    expect(empty.find('[data-testid="empty-create-team"]').exists()).toBe(true);
    expect(empty.find('[data-testid="empty-join-team"]').exists()).toBe(true);
  });

  it('shows an error state when loading teams fails', async () => {
    vi.mocked(listTeams).mockRejectedValue(new Error('network down'));
    const { wrapper } = await mountView();
    expect(wrapper.text()).toContain('加载失败');
    expect(wrapper.find('[data-testid="retry-button"]').exists()).toBe(true);
  });

  it('opens the create-team modal, then closes it and refreshes the list on created', async () => {
    vi.mocked(listTeams)
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([sampleTeam]);
    const { wrapper } = await mountView();

    expect(wrapper.find('[data-testid="create-team-modal-stub"]').exists()).toBe(false);
    await wrapper.find('[data-testid="create-team-button"]').trigger('click');
    expect(wrapper.find('[data-testid="create-team-modal-stub"]').exists()).toBe(true);

    await wrapper.find('[data-testid="stub-create-team"]').trigger('click');
    await flushPromises();

    expect(vi.mocked(listTeams)).toHaveBeenCalledTimes(2);
    expect(wrapper.find('[data-testid="create-team-modal-stub"]').exists()).toBe(false);
    expect(wrapper.findAll('[data-testid="team-item"]')).toHaveLength(1);
  });

  it('refreshes my teams after a join while keeping the join modal open', async () => {
    vi.mocked(listTeams)
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([sampleTeam]);
    const { wrapper } = await mountView();

    await wrapper.find('[data-testid="join-team-button"]').trigger('click');
    expect(wrapper.find('[data-testid="join-team-modal-stub"]').exists()).toBe(true);

    await wrapper.find('[data-testid="stub-join-team"]').trigger('click');
    await flushPromises();

    expect(vi.mocked(listTeams)).toHaveBeenCalledTimes(2);
    expect(wrapper.find('[data-testid="join-team-modal-stub"]').exists()).toBe(true);
    expect(wrapper.findAll('[data-testid="team-item"]')).toHaveLength(1);
  });

  it('opens the corresponding modals from the empty-state entries', async () => {
    vi.mocked(listTeams).mockResolvedValue([]);
    const { wrapper } = await mountView();

    await wrapper.find('[data-testid="empty-create-team"]').trigger('click');
    expect(wrapper.find('[data-testid="create-team-modal-stub"]').exists()).toBe(true);

    await wrapper.find('[data-testid="empty-join-team"]').trigger('click');
    expect(wrapper.find('[data-testid="join-team-modal-stub"]').exists()).toBe(true);
  });
});
