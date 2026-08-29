import { describe, expect, it } from 'vitest';
import { mount } from '@vue/test-utils';
import RegisterErrorBanner from '../src/components/RegisterErrorBanner.vue';

function mountBanner(message = '自动注册失败,请稍后重试') {
  return mount(RegisterErrorBanner, { props: { message } });
}

describe('RegisterErrorBanner', () => {
  it('renders the error message', () => {
    const wrapper = mountBanner();
    expect(wrapper.find('[data-testid="register-error-banner"]').exists()).toBe(true);
    expect(wrapper.text()).toContain('自动注册失败,请稍后重试');
  });

  it('emits close when the close button is clicked', async () => {
    const wrapper = mountBanner();
    await wrapper.find('[data-testid="banner-close"]').trigger('click');
    expect(wrapper.emitted('close')).toHaveLength(1);
  });

  it('emits retry when the retry button is clicked', async () => {
    const wrapper = mountBanner();
    await wrapper.find('[data-testid="banner-retry"]').trigger('click');
    expect(wrapper.emitted('retry')).toHaveLength(1);
  });
});
