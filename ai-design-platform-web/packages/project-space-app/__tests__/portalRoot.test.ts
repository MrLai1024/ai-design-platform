import { afterEach, describe, expect, it } from 'vitest';
import { mount } from '@vue/test-utils';
import ProjectCreateModal from '../src/components/ProjectCreateModal.vue';
import { getAppRoot, setAppRoot } from '../src/portal-root';

/**
 * Regression: antd modals teleport to document.body by default, which under
 * qiankun lands them OUTSIDE the app wrapper and outside the scope of the
 * scopedCSS-prefixed rules (`div[data-qiankun="..."] .ant-modal-...`) — the
 * modal renders completely unstyled. The modals must render into the mounted
 * app root (set by main.ts render() via setAppRoot).
 */
describe('portal-root', () => {
  afterEach(() => {
    setAppRoot(null as unknown as HTMLElement);
    document.body.innerHTML = '';
  });

  it('getAppRoot falls back to document.body when unset', () => {
    expect(getAppRoot()).toBe(document.body);
  });

  it('modal renders inside the configured app root', async () => {
    const root = document.createElement('div');
    document.body.appendChild(root);
    setAppRoot(root);

    const wrapper = mount(ProjectCreateModal, {
      props: { open: true },
      attachTo: root,
    });
    await wrapper.vm.$nextTick();
    // antd v4 cssinjs/portal renders the modal asynchronously; give it a tick
    await new Promise((r) => setTimeout(r, 50));

    // exactly one modal, and it must live inside the app root (which is what
    // keeps it inside the qiankun wrapper in the real app)
    const modals = document.querySelectorAll('.ant-modal');
    expect(modals.length).toBe(1);
    expect(root.contains(modals[0])).toBe(true);

    wrapper.unmount();
  });
});
