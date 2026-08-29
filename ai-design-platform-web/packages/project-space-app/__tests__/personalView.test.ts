import { beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent } from 'vue';
import { flushPromises, mount } from '@vue/test-utils';
import { createMemoryHistory, createRouter } from 'vue-router';
import PersonalView from '../src/views/PersonalView.vue';
import { routes, ROUTE_NAMES } from '../src/router';
import { listProjects } from '@ai-design/shared';
import type { Project } from '@ai-design/shared';

vi.mock('@ai-design/shared', () => ({
  listProjects: vi.fn(),
}));

const sampleProject: Project = {
  id: 'p1',
  name: '演示项目',
  description: '演示',
  level: 'demo',
  teamId: null,
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

async function mountView() {
  const router = createRouter({ history: createMemoryHistory(), routes });
  await router.push('/personal');
  await router.isReady();
  const wrapper = mount(PersonalView, {
    global: { plugins: [router], stubs: { ProjectCreateModal: ProjectCreateModalStub } },
  });
  await flushPromises();
  return { wrapper, router };
}

beforeEach(() => {
  vi.mocked(listProjects).mockReset();
});

describe('PersonalView', () => {
  it('renders the project list with name, level tag and description', async () => {
    vi.mocked(listProjects).mockResolvedValue([
      sampleProject,
      { ...sampleProject, id: 'p2', name: '生产项目', description: '', level: 'production' },
    ]);
    const { wrapper } = await mountView();

    const items = wrapper.findAll('[data-testid="project-item"]');
    expect(items).toHaveLength(2);
    expect(items[0].text()).toContain('演示项目');
    expect(items[0].text()).toContain('演示级');
    expect(items[0].text()).toContain('演示');
    expect(items[1].text()).toContain('生产项目');
    expect(items[1].text()).toContain('生产级');
  });

  it('shows the empty state with a 新建项目 button when there are no projects', async () => {
    vi.mocked(listProjects).mockResolvedValue([]);
    const { wrapper } = await mountView();

    const empty = wrapper.find('[data-testid="empty-state"]');
    expect(empty.exists()).toBe(true);
    expect(empty.text()).toContain('暂无个人项目');
    expect(empty.find('button').text().replace(/\s/g, '')).toContain('新建项目');
  });

  it('shows an error state with a retry button that reloads the list', async () => {
    vi.mocked(listProjects)
      .mockRejectedValueOnce(new Error('network down'))
      .mockResolvedValueOnce([sampleProject]);
    const { wrapper } = await mountView();

    expect(wrapper.text()).toContain('加载失败');
    expect(wrapper.find('[data-testid="retry-button"]').exists()).toBe(true);

    await wrapper.find('[data-testid="retry-button"]').trigger('click');
    await flushPromises();
    expect(wrapper.findAll('[data-testid="project-item"]')).toHaveLength(1);
  });

  it('navigates to the project detail when a list item is clicked', async () => {
    vi.mocked(listProjects).mockResolvedValue([sampleProject]);
    const { wrapper, router } = await mountView();

    await wrapper.find('[data-testid="project-item"]').trigger('click');
    await flushPromises();

    expect(router.currentRoute.value.name).toBe(ROUTE_NAMES.PROJECT_DETAIL);
    expect(router.currentRoute.value.params.id).toBe('p1');
    expect(router.currentRoute.value.query).toEqual({});
  });

  it('opens the create modal (no teamId), then closes it and refreshes the list on created', async () => {
    vi.mocked(listProjects)
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([sampleProject]);
    const { wrapper } = await mountView();

    expect(wrapper.find('[data-testid="create-modal-stub"]').exists()).toBe(false);
    await wrapper.find('[data-testid="create-project-button"]').trigger('click');
    expect(wrapper.find('[data-testid="create-modal-stub"]').exists()).toBe(true);
    expect(wrapper.findComponent(ProjectCreateModalStub).props('teamId')).toBeNull();

    await wrapper.find('[data-testid="stub-create"]').trigger('click');
    await flushPromises();

    expect(vi.mocked(listProjects)).toHaveBeenCalledTimes(2);
    expect(wrapper.find('[data-testid="create-modal-stub"]').exists()).toBe(false);
    expect(wrapper.findAll('[data-testid="project-item"]')).toHaveLength(1);
  });
});
