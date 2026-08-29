import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import TeamCreateModal from '../src/components/TeamCreateModal.vue';
import { createTeam } from '@ai-design/shared';
import type { Team } from '@ai-design/shared';
import { bodyQuery, cleanupAntdModals, findBodyButton, flushAntdFormDebounce } from './helpers/antd';

vi.mock('@ai-design/shared', () => ({
  createTeam: vi.fn(),
}));

const sampleTeam: Team = {
  id: 't1',
  name: '星辰团队',
  ownerId: 'u1',
  createdAt: '2026-08-01',
};

function mountModal(props: Record<string, unknown> = {}) {
  return mount(TeamCreateModal, { props: { open: true, ...props } });
}

beforeEach(() => {
  vi.mocked(createTeam).mockReset().mockResolvedValue(sampleTeam);
});

afterEach(() => {
  cleanupAntdModals();
});

describe('TeamCreateModal', () => {
  it('blocks submission and shows a validation message when the name is empty', async () => {
    mountModal();
    await findBodyButton('创建').trigger('click');
    await flushPromises();
    await flushAntdFormDebounce();
    expect(vi.mocked(createTeam)).not.toHaveBeenCalled();
    expect(document.body.textContent).toContain('请输入团队名称');
  });

  it('blocks submission and shows a validation message when the name is only whitespace', async () => {
    mountModal();
    await bodyQuery('input[placeholder="请输入团队名称"]').setValue('   ');
    await findBodyButton('创建').trigger('click');
    await flushPromises();
    await flushAntdFormDebounce();
    expect(vi.mocked(createTeam)).not.toHaveBeenCalled();
    expect(document.body.textContent).toContain('请输入团队名称');
  });

  it('submits the trimmed team name and emits created', async () => {
    const wrapper = mountModal();
    await bodyQuery('input[placeholder="请输入团队名称"]').setValue('  星辰团队  ');
    await findBodyButton('创建').trigger('click');
    await flushPromises();

    expect(vi.mocked(createTeam)).toHaveBeenCalledWith({ name: '星辰团队' });
    expect(wrapper.emitted('created')![0]).toEqual([sampleTeam]);
  });

  it('shows an inline error when creation fails', async () => {
    vi.mocked(createTeam).mockRejectedValue(new Error('boom'));
    const wrapper = mountModal();
    await bodyQuery('input[placeholder="请输入团队名称"]').setValue('新团队');
    await findBodyButton('创建').trigger('click');
    await flushPromises();

    expect(document.body.textContent).toContain('创建团队失败');
    expect(wrapper.emitted('created')).toBeUndefined();
  });

  it('emits cancel when the cancel button is clicked', async () => {
    const wrapper = mountModal();
    await findBodyButton('取消').trigger('click');
    expect(wrapper.emitted('cancel')).toHaveLength(1);
  });
});
