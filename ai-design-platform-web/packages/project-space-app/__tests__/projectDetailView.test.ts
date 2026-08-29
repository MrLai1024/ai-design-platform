import { describe, expect, it } from 'vitest';
import { mount } from '@vue/test-utils';
import ProjectDetailView from '../src/views/ProjectDetailView.vue';

function mountView() {
  return mount(ProjectDetailView);
}

describe('ProjectDetailView', () => {
  it('renders the Issue and 代码仓 menu items', () => {
    const wrapper = mountView();
    const items = wrapper.findAll('.ant-menu-item');
    expect(items.map((i) => i.text())).toEqual(['Issue', '代码仓']);
  });

  it('shows the Issue content by default with placeholder', () => {
    const wrapper = mountView();
    expect(wrapper.find('.ant-menu-item-selected').text()).toBe('Issue');
    expect(wrapper.find('[data-testid="issues-placeholder"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="issues-placeholder"]').text()).toContain('开发中');
  });

  it('switches to the 代码仓 content with its own placeholder', async () => {
    const wrapper = mountView();
    await wrapper.findAll('.ant-menu-item')[1].trigger('click');
    expect(wrapper.find('.ant-menu-item-selected').text()).toBe('代码仓');
    expect(wrapper.find('[data-testid="repo-placeholder"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="issues-placeholder"]').exists()).toBe(false);
  });
});
