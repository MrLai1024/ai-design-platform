import { describe, expect, it } from 'vitest';
import { mount } from '@vue/test-utils';
import ProjectDetailView from '../src/views/ProjectDetailView.vue';

function mountView() {
  return mount(ProjectDetailView);
}

describe('ProjectDetailView', () => {
  it('renders the Issue and 代码仓 tabs', () => {
    const wrapper = mountView();
    const tabs = wrapper.findAll('.ant-tabs-tab');
    expect(tabs.map((t) => t.text())).toEqual(['Issue', '代码仓']);
  });

  it('shows the Issue tab by default with placeholder content', () => {
    const wrapper = mountView();
    expect(wrapper.find('.ant-tabs-tab-active').text()).toBe('Issue');
    expect(wrapper.find('[data-testid="issues-placeholder"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="issues-placeholder"]').text()).toContain('开发中');
  });

  it('switches to the 代码仓 tab with its own placeholder', async () => {
    const wrapper = mountView();
    await wrapper.findAll('.ant-tabs-tab')[1].trigger('click');
    expect(wrapper.find('.ant-tabs-tab-active').text()).toBe('代码仓');
    expect(wrapper.find('[data-testid="repo-placeholder"]').exists()).toBe(true);
  });
});
