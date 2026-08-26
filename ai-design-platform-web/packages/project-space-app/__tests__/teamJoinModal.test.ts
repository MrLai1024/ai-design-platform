import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import TeamJoinModal from '../src/components/TeamJoinModal.vue';
import { joinTeam, searchTeams } from '@ai-design/shared';
import type { Team } from '@ai-design/shared';
import { bodyQuery, bodyQueryAll, cleanupAntdModals, findBodyButton, flushAntdFormDebounce } from './helpers/antd';

vi.mock('@ai-design/shared', () => ({
  searchTeams: vi.fn(),
  joinTeam: vi.fn(),
}));

const sampleTeam: Team = {
  id: 't1',
  name: '星辰团队',
  description: '前端小组',
  ownerId: 'u1',
  createdAt: '2026-08-01',
};

const designTeam: Team = {
  id: 't2',
  name: '设计团队',
  ownerId: 'u2',
  createdAt: '2026-08-01',
};

function mountModal(props: Record<string, unknown> = {}) {
  return mount(TeamJoinModal, { props: { open: true, ...props } });
}

async function search(keyword: string) {
  await bodyQuery('input[placeholder="输入团队名称关键字搜索"]').setValue(keyword);
  await bodyQuery('.ant-input-search-button').trigger('click');
  await flushPromises();
}

beforeEach(() => {
  vi.mocked(searchTeams).mockReset();
  vi.mocked(joinTeam).mockReset();
});

afterEach(() => {
  cleanupAntdModals();
});

describe('TeamJoinModal', () => {
  it('searches teams by keyword and renders the results with 加入 buttons', async () => {
    vi.mocked(searchTeams).mockResolvedValue([sampleTeam]);
    mountModal();

    await search('星辰');

    expect(vi.mocked(searchTeams)).toHaveBeenCalledWith('星辰');
    const results = bodyQueryAll('[data-testid="join-result-item"]');
    expect(results).toHaveLength(1);
    expect(results[0].text()).toContain('星辰团队');
    expect(results[0].text()).toContain('前端小组');
    expect(findBodyButton('加入').exists()).toBe(true);
  });

  it('shows an empty result state when nothing matches', async () => {
    vi.mocked(searchTeams).mockResolvedValue([]);
    mountModal();
    await search('不存在');
    expect(document.body.textContent).toContain('未找到匹配的团队');
  });

  it('shows an error when the search fails', async () => {
    vi.mocked(searchTeams).mockRejectedValue(new Error('network down'));
    mountModal();
    await search('星辰');
    expect(document.body.textContent).toContain('搜索失败');
  });

  it('discards a stale search response that resolves after a newer search', async () => {
    let resolveOld!: (value: Team[]) => void;
    vi.mocked(searchTeams)
      .mockImplementationOnce(
        () =>
          new Promise<Team[]>((resolve) => {
            resolveOld = resolve;
          }),
      )
      .mockResolvedValueOnce([designTeam]);
    mountModal();

    // old search — stays pending, results area keeps spinning
    await search('旧关键字');
    await flushAntdFormDebounce(); // antd Spin debounces its spinning class via setTimeout
    expect(document.body.querySelector('.ant-spin-spinning')).not.toBeNull();

    // newer search with a refined keyword — resolves first
    await search('新关键字');

    expect(vi.mocked(searchTeams)).toHaveBeenCalledTimes(2);
    const results = bodyQueryAll('[data-testid="join-result-item"]');
    expect(results).toHaveLength(1);
    expect(results[0].text()).toContain('设计团队');
    expect(document.body.textContent).not.toContain('搜索失败');

    // the old search resolves late with different data — must be ignored
    resolveOld([sampleTeam]);
    await flushPromises();
    await flushAntdFormDebounce();

    const after = bodyQueryAll('[data-testid="join-result-item"]');
    expect(after).toHaveLength(1);
    expect(after[0].text()).toContain('设计团队');
    expect(after[0].text()).not.toContain('星辰团队');
    expect(document.body.textContent).not.toContain('搜索失败');
    // searching state is owned by the newest search only — settled by now
    expect(document.body.querySelector('.ant-spin-spinning')).toBeNull();
  });

  it('clears the spinning state when reopened after an in-flight search', async () => {
    let resolveSearch!: (value: Team[]) => void;
    vi.mocked(searchTeams).mockImplementationOnce(
      () =>
        new Promise<Team[]>((resolve) => {
          resolveSearch = resolve;
        }),
    );
    const wrapper = mountModal();

    // search stays pending — the results area spins
    await search('星辰');
    await flushAntdFormDebounce();
    expect(document.body.querySelector('.ant-spin-spinning')).not.toBeNull();

    // close and reopen while the old search is still in flight
    await wrapper.setProps({ open: false });
    await wrapper.setProps({ open: true });
    await flushPromises();
    await flushAntdFormDebounce();
    expect(document.body.querySelector('.ant-spin-spinning')).toBeNull();

    // the stale search resolving late must not revive the spinner
    resolveSearch([sampleTeam]);
    await flushPromises();
    await flushAntdFormDebounce();
    expect(document.body.querySelector('.ant-spin-spinning')).toBeNull();
  });

  it('joins a team, removes it from the results and emits joined', async () => {
    vi.mocked(searchTeams).mockResolvedValue([sampleTeam]);
    vi.mocked(joinTeam).mockResolvedValue(undefined);
    const wrapper = mountModal();

    await search('星辰');
    await findBodyButton('加入').trigger('click');
    await flushPromises();

    expect(vi.mocked(joinTeam)).toHaveBeenCalledWith('t1');
    expect(wrapper.emitted('joined')![0]).toEqual([sampleTeam]);
    // joined team disappears from the result list
    expect(bodyQueryAll('[data-testid="join-result-item"]')).toHaveLength(0);
  });

  it('shows a friendly message on a 409 duplicate join and keeps the result', async () => {
    vi.mocked(searchTeams).mockResolvedValue([sampleTeam]);
    vi.mocked(joinTeam).mockRejectedValue({ response: { status: 409 } });
    mountModal();

    await search('星辰');
    await findBodyButton('加入').trigger('click');
    await flushPromises();

    expect(document.body.textContent).toContain('已加入该团队');
    expect(bodyQueryAll('[data-testid="join-result-item"]')).toHaveLength(1);
  });

  it('shows a generic error on a non-409 join failure', async () => {
    vi.mocked(searchTeams).mockResolvedValue([sampleTeam]);
    vi.mocked(joinTeam).mockRejectedValue(new Error('boom'));
    mountModal();

    await search('星辰');
    await findBodyButton('加入').trigger('click');
    await flushPromises();

    expect(document.body.textContent).toContain('加入失败');
    expect(document.body.textContent).not.toContain('已加入该团队');
  });

  it('filters teams joined during the session out of later search results', async () => {
    vi.mocked(searchTeams).mockResolvedValue([sampleTeam]);
    vi.mocked(joinTeam).mockResolvedValue(undefined);
    mountModal();

    await search('星辰');
    await findBodyButton('加入').trigger('click');
    await flushPromises();

    // search again with the same keyword — the joined team must not reappear
    await bodyQuery('.ant-input-search-button').trigger('click');
    await flushPromises();
    expect(bodyQueryAll('[data-testid="join-result-item"]')).toHaveLength(0);
    expect(document.body.textContent).toContain('未找到匹配的团队');
  });

  it('emits cancel when the modal is closed', async () => {
    const wrapper = mountModal();
    await bodyQuery('.ant-modal-close').trigger('click');
    expect(wrapper.emitted('cancel')).toHaveLength(1);
  });
});
