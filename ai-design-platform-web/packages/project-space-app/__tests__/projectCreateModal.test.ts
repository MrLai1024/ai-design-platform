import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils';
import ProjectCreateModal from '../src/components/ProjectCreateModal.vue';
import { createProject } from '@ai-design/shared';
import type { Project } from '@ai-design/shared';
import { bodyQuery, bodyQueryAll, cleanupAntdModals, findBodyButton, flushAntdFormDebounce } from './helpers/antd';

vi.mock('@ai-design/shared', () => ({
  createProject: vi.fn(),
}));

const sampleProject: Project = {
  id: 'p1',
  name: '新项目',
  level: 'demo',
  teamId: null,
  createdBy: 'u1',
  createdAt: '2026-08-01',
};

function mountModal(props: Record<string, unknown> = {}) {
  return mount(ProjectCreateModal, {
    props: { open: true, ...props },
  });
}

async function fillNameAndSubmit(wrapper: VueWrapper, name: string) {
  await bodyQuery('input[placeholder="请输入项目名称"]').setValue(name);
  await findBodyButton('创建').trigger('click');
  await flushPromises();
}

beforeEach(() => {
  vi.mocked(createProject).mockReset().mockResolvedValue(sampleProject);
});

afterEach(() => {
  cleanupAntdModals();
});

describe('ProjectCreateModal', () => {
  it('renders name/description fields and a level radio group defaulting to 演示级', () => {
    mountModal();
    expect(bodyQuery('input[placeholder="请输入项目名称"]').exists()).toBe(true);
    expect(bodyQuery('textarea[placeholder="项目简介(选填)"]').exists()).toBe(true);

    const radios = bodyQueryAll('.ant-radio-wrapper');
    expect(radios.map((r) => r.text())).toEqual(['演示级', '生产级']);
    expect(bodyQuery('.ant-radio-wrapper-checked').text()).toBe('演示级');
  });

  it('blocks submission and shows a validation message when the name is empty', async () => {
    mountModal();
    await findBodyButton('创建').trigger('click');
    await flushPromises();
    await flushAntdFormDebounce();
    expect(vi.mocked(createProject)).not.toHaveBeenCalled();
    expect(document.body.textContent).toContain('请输入项目名称');
  });

  it('blocks submission and shows a validation message when the name is only whitespace', async () => {
    mountModal();
    await bodyQuery('input[placeholder="请输入项目名称"]').setValue('   ');
    await findBodyButton('创建').trigger('click');
    await flushPromises();
    await flushAntdFormDebounce();
    expect(vi.mocked(createProject)).not.toHaveBeenCalled();
    expect(document.body.textContent).toContain('请输入项目名称');
  });

  it('submits a personal project with the default level and omits teamId', async () => {
    const wrapper = mountModal();
    await fillNameAndSubmit(wrapper, '个人项目A');

    expect(vi.mocked(createProject)).toHaveBeenCalledTimes(1);
    const payload = vi.mocked(createProject).mock.calls[0][0];
    expect(payload).toEqual({ name: '个人项目A', level: 'demo' });
    expect('teamId' in payload).toBe(false);
    expect(wrapper.emitted('created')![0]).toEqual([sampleProject]);
  });

  it('includes the optional description in the payload', async () => {
    const wrapper = mountModal();
    await bodyQuery('input[placeholder="请输入项目名称"]').setValue('带简介的项目');
    await bodyQuery('textarea[placeholder="项目简介(选填)"]').setValue('一段简介');
    await findBodyButton('创建').trigger('click');
    await flushPromises();

    const payload = vi.mocked(createProject).mock.calls[0][0];
    expect(payload).toEqual({ name: '带简介的项目', description: '一段简介', level: 'demo' });
  });

  it('submits the selected production level', async () => {
    const wrapper = mountModal();
    await bodyQuery('input[placeholder="请输入项目名称"]').setValue('生产项目');
    await bodyQueryAll('input[type="radio"]')[1].setValue();
    await findBodyButton('创建').trigger('click');
    await flushPromises();

    const payload = vi.mocked(createProject).mock.calls[0][0];
    expect(payload).toEqual({ name: '生产项目', level: 'production' });
  });

  it('passes teamId through when creating a project inside a team', async () => {
    const wrapper = mountModal({ teamId: 'team-9' });
    await fillNameAndSubmit(wrapper, '团队项目B');

    const payload = vi.mocked(createProject).mock.calls[0][0];
    expect(payload.teamId).toBe('team-9');
  });

  it('shows an inline error and stays open when creation fails', async () => {
    vi.mocked(createProject).mockRejectedValue(new Error('boom'));
    const wrapper = mountModal();
    await fillNameAndSubmit(wrapper, '失败项目');

    expect(document.body.textContent).toContain('创建项目失败');
    expect(wrapper.emitted('created')).toBeUndefined();
  });

  it('emits cancel when the cancel button is clicked', async () => {
    const wrapper = mountModal();
    await findBodyButton('取消').trigger('click');
    expect(wrapper.emitted('cancel')).toHaveLength(1);
  });

  it('resets the form when reopened', async () => {
    const wrapper = mountModal();
    await bodyQuery('input[placeholder="请输入项目名称"]').setValue('旧名称');
    await wrapper.setProps({ open: false });
    await wrapper.setProps({ open: true });
    await flushPromises();

    const input = bodyQuery('input[placeholder="请输入项目名称"]').element as HTMLInputElement;
    expect(input.value).toBe('');
    expect(bodyQuery('.ant-radio-wrapper-checked').text()).toBe('演示级');
  });
});
