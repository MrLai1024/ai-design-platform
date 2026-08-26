import { describe, expect, it } from 'vitest';
import { mount } from '@vue/test-utils';
import AccountEntry from '../src/components/AccountEntry.vue';

function mountEntry(props: Partial<{ account: string | null; password: string | null }> = {}) {
  return mount(AccountEntry, {
    props: { account: null, password: null, ...props },
    global: { stubs: { teleport: true } },
  });
}

describe('AccountEntry', () => {
  it('shows a default avatar and no account name when no credentials exist', () => {
    const wrapper = mountEntry();
    expect(wrapper.find('[data-testid="account-entry"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="account-name"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="account-entry"]').text()).toContain('👤');
  });

  it('shows the account name once credentials are ready', () => {
    const wrapper = mountEntry({ account: 'user_abc123', password: 'p@ssw0rd' });
    expect(wrapper.find('[data-testid="account-name"]').text()).toBe('user_abc123');
  });

  it('opens the modal on click and displays account and password', async () => {
    const wrapper = mountEntry({ account: 'user_abc123', password: 'p@ssw0rd' });
    expect(wrapper.find('[data-testid="account-modal"]').exists()).toBe(false);

    await wrapper.find('[data-testid="account-entry"]').trigger('click');
    const modal = wrapper.find('[data-testid="account-modal"]');
    expect(modal.exists()).toBe(true);
    expect(modal.text()).toContain('user_abc123');
    expect(modal.text()).toContain('p@ssw0rd');
  });

  it('closes the modal via the close button', async () => {
    const wrapper = mountEntry({ account: 'user_abc123', password: 'p@ssw0rd' });
    await wrapper.find('[data-testid="account-entry"]').trigger('click');
    expect(wrapper.find('[data-testid="account-modal"]').exists()).toBe(true);

    await wrapper.find('[data-testid="account-modal-close"]').trigger('click');
    expect(wrapper.find('[data-testid="account-modal"]').exists()).toBe(false);
  });

  it('closes the modal via backdrop click', async () => {
    const wrapper = mountEntry({ account: 'user_abc123', password: 'p@ssw0rd' });
    await wrapper.find('[data-testid="account-entry"]').trigger('click');
    expect(wrapper.find('[data-testid="account-modal"]').exists()).toBe(true);

    await wrapper.find('[data-testid="account-modal-backdrop"]').trigger('click');
    expect(wrapper.find('[data-testid="account-modal"]').exists()).toBe(false);
  });

  it('shows placeholders in the modal when no credentials exist yet', async () => {
    const wrapper = mountEntry();
    await wrapper.find('[data-testid="account-entry"]').trigger('click');
    const modal = wrapper.find('[data-testid="account-modal"]');
    expect(modal.exists()).toBe(true);
    expect(modal.text()).toContain('—');
  });
});
