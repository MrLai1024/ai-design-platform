import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import { createMemoryHistory, createRouter } from 'vue-router';
import AppLayout from '../src/layouts/AppLayout.vue';
import { routes, ROUTE_NAMES } from '../src/router';
import { getProject, listTeams } from '@ai-design/shared';

vi.mock('@ai-design/shared', () => ({
  listTeams: vi.fn(),
  getProject: vi.fn(),
}));

const sampleTeam = { id: 't1', name: '星辰团队', ownerId: 'u1', createdAt: '2026-08-01' };
const sampleProject = {
  id: 'p1',
  name: '演示项目',
  level: 'demo' as const,
  teamId: null,
  createdBy: 'u1',
  createdAt: '2026-08-01',
};

// antd's Sider/Menu rely on a few browser APIs in happy-dom
beforeAll(() => {
  if (!window.matchMedia) {
    window.matchMedia = ((query: string) => ({
      matches: false,
      media: query,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      addListener: () => undefined,
      removeListener: () => undefined,
      onchange: null,
      dispatchEvent: () => false,
    })) as unknown as typeof window.matchMedia;
  }
  if (!(globalThis as { ResizeObserver?: unknown }).ResizeObserver) {
    (globalThis as { ResizeObserver?: unknown }).ResizeObserver = class {
      observe(): void {}
      unobserve(): void {}
      disconnect(): void {}
    };
  }
});

beforeEach(() => {
  vi.mocked(listTeams).mockReset().mockResolvedValue([sampleTeam]);
  vi.mocked(getProject).mockReset().mockResolvedValue(sampleProject);
});

async function mountLayout(path: string) {
  const router = createRouter({ history: createMemoryHistory(), routes });
  await router.push(path);
  await router.isReady();
  const wrapper = mount(AppLayout, {
    global: {
      plugins: [router],
    },
    slots: { default: '<div data-testid="slot-content">content</div>' },
  });
  await wrapper.vm.$nextTick();
  return { wrapper, router };
}

describe('AppLayout', () => {
  it('renders the side menu with the two entries and the derived breadcrumb', async () => {
    const { wrapper } = await mountLayout('/personal');
    const menuItems = wrapper.findAll('.ant-menu-item');
    expect(menuItems.map((i) => i.text())).toEqual(['个人项目', '团队项目']);

    const breadcrumb = wrapper.find('.ant-breadcrumb');
    expect(breadcrumb.text()).toContain('首页');
    expect(breadcrumb.text()).toContain('项目空间');
    expect(breadcrumb.text()).toContain('个人项目');
    expect(wrapper.find('[data-testid="slot-content"]').exists()).toBe(true);
  });

  it('selects the 团队项目 menu item on team routes', async () => {
    const { wrapper } = await mountLayout('/teams');
    const selected = wrapper.find('.ant-menu-item-selected');
    expect(selected.exists()).toBe(true);
    expect(selected.text()).toBe('团队项目');
  });

  it('selects the 团队项目 menu item on team detail routes', async () => {
    const { wrapper } = await mountLayout('/teams/t1');
    const selected = wrapper.find('.ant-menu-item-selected');
    expect(selected.text()).toBe('团队项目');
  });

  it('clicking a menu item navigates to the corresponding route', async () => {
    const { wrapper, router } = await mountLayout('/personal');
    const menuItems = wrapper.findAll('.ant-menu-item');
    await menuItems[1].trigger('click');
    await flushPromises();
    expect(router.currentRoute.value.name).toBe(ROUTE_NAMES.TEAMS);
  });

  it('clicking 项目空间 in the breadcrumb navigates back to /personal', async () => {
    const { wrapper, router } = await mountLayout('/teams');
    const crumbLinks = wrapper.findAll('.ant-breadcrumb a');
    // 首页 is the first link (external), 项目空间 is the second
    await crumbLinks[1].trigger('click');
    await flushPromises();
    expect(router.currentRoute.value.name).toBe(ROUTE_NAMES.PERSONAL);
  });

  it('selects the 团队项目 menu item on project detail opened from a team (?from=team)', async () => {
    const { wrapper } = await mountLayout('/projects/p1?from=team');
    const selected = wrapper.find('.ant-menu-item-selected');
    expect(selected.exists()).toBe(true);
    expect(selected.text()).toBe('团队项目');
  });
});

describe('AppLayout — breadcrumb name resolution', () => {
  it('resolves the team name for team project pages', async () => {
    const { wrapper } = await mountLayout('/teams/t1');
    await flushPromises();
    expect(vi.mocked(listTeams)).toHaveBeenCalled();
    expect(wrapper.find('.ant-breadcrumb').text()).toContain('星辰团队');
  });

  it('resolves project and team names for a team-sourced project detail', async () => {
    const { wrapper } = await mountLayout('/projects/p1?from=team&teamId=t1');
    await flushPromises();
    const breadcrumb = wrapper.find('.ant-breadcrumb').text();
    expect(vi.mocked(getProject)).toHaveBeenCalledWith('p1');
    expect(vi.mocked(listTeams)).toHaveBeenCalled();
    expect(breadcrumb).toContain('演示项目');
    expect(breadcrumb).toContain('星辰团队');
    expect(breadcrumb).toContain('团队项目');
  });

  it('resolves only the project name for a personal-sourced project detail', async () => {
    const { wrapper } = await mountLayout('/projects/p1');
    await flushPromises();
    expect(vi.mocked(getProject)).toHaveBeenCalledWith('p1');
    expect(vi.mocked(listTeams)).not.toHaveBeenCalled();
    const breadcrumb = wrapper.find('.ant-breadcrumb').text();
    expect(breadcrumb).toContain('演示项目');
    expect(breadcrumb).toContain('个人项目');
  });

  it('falls back to placeholder labels when name resolution fails', async () => {
    vi.mocked(getProject).mockRejectedValue(new Error('network down'));
    vi.mocked(listTeams).mockRejectedValue(new Error('network down'));
    const { wrapper } = await mountLayout('/projects/p1?from=team&teamId=t1');
    await flushPromises();
    const breadcrumb = wrapper.find('.ant-breadcrumb').text();
    expect(breadcrumb).toContain('项目');
    expect(breadcrumb).toContain('团队');
  });

  it('a stale failed team lookup does not clear a newer resolved team name', async () => {
    const otherTeam = { ...sampleTeam, id: 't2', name: '北极星团队' };
    let rejectOld!: (error: unknown) => void;
    vi.mocked(listTeams)
      .mockImplementationOnce(
        () =>
          new Promise((_resolve, reject) => {
            rejectOld = reject;
          }),
      )
      .mockResolvedValueOnce([otherTeam]);

    const { wrapper, router } = await mountLayout('/teams/t1');
    await flushPromises();
    // first lookup for t1 is still pending — navigate to another team
    await router.push('/teams/t2');
    await flushPromises();
    expect(wrapper.find('.ant-breadcrumb').text()).toContain('北极星团队');

    // the old request fails late — it must not clear the new team name
    rejectOld(new Error('network down'));
    await flushPromises();
    const breadcrumb = wrapper.find('.ant-breadcrumb').text();
    expect(breadcrumb).toContain('北极星团队');
    expect(breadcrumb).not.toContain('星辰团队');
  });
});
