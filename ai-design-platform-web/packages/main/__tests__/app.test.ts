import { beforeEach, describe, expect, it } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import { createMemoryHistory, createRouter, type Router } from 'vue-router';
import { http } from '@ai-design/shared';
import App from '../src/App.vue';
import { routes } from '../src/router';

const sample = { account: 'user_abc123', password: 'p@ssw0rd', token: 'jwt-token' };

let router: Router;

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem('ai_design_account', JSON.stringify(sample));
  router = createRouter({ history: createMemoryHistory(), routes });
});

async function mountApp(path = '/ai-chat') {
  router.push(path);
  await router.isReady();
  const wrapper = mount(App, {
    global: { plugins: [router], stubs: { teleport: true } },
  });
  // Flush onMounted init() + reactive updates
  await wrapper.vm.$nextTick();
  await wrapper.vm.$nextTick();
  return wrapper;
}

describe('App base layout', () => {
  it('hides the header on the home route', async () => {
    const wrapper = await mountApp('/');
    expect(wrapper.find('header').exists()).toBe(false);
    expect(wrapper.find('[data-testid="account-entry"]').exists()).toBe(false);
  });

  it('renders the personal info entry as the last item of the header (after all nav items)', async () => {
    const wrapper = await mountApp('/ai-chat');
    const header = wrapper.find('header');
    expect(header.exists()).toBe(true);

    const flexContainer = header.find('div');
    const children = Array.from(flexContainer.element.children) as HTMLElement[];
    expect(children.length).toBe(2);
    // First child is the nav with all menu items, second is the account entry
    expect(children[0].tagName.toLowerCase()).toBe('nav');
    expect(children[1].dataset.testid).toBe('account-entry-wrap');

    // All five menu links live inside the nav, in order
    const links = flexContainer.findAll('nav a');
    expect(links.map((l) => l.text().trim())).toEqual([
      '首页',
      'AI 对话',
      'AI 生成',
      'AI 工作流',
      '项目空间',
    ]);
  });

  it('shows the account name in the entry after init and no error banner', async () => {
    const wrapper = await mountApp('/ai-chat');
    expect(wrapper.find('[data-testid="account-name"]').text()).toBe('user_abc123');
    expect(wrapper.find('[data-testid="register-error-banner"]').exists()).toBe(false);
  });

  it('pre-renders all sub-app containers including the project space one', async () => {
    const wrapper = await mountApp('/ai-chat');
    for (const id of [
      '#sub-app-chat',
      '#sub-app-generation',
      '#sub-app-workflow',
      '#sub-app-project-space',
    ]) {
      expect(wrapper.find(id).exists()).toBe(true);
    }
  });

  it('re-registers automatically after a 401 wipes the credentials (AUTH_UNAUTHORIZED recovery)', async () => {
    const wrapper = await mountApp('/ai-chat');
    expect(wrapper.find('[data-testid="account-name"]').text()).toBe('user_abc123');

    const newSample = { account: 'user_new999', password: 'p@ss-new', token: 'jwt-new' };
    http.defaults.adapter = (config: { url?: string }) =>
      config.url === '/v1/teams'
        ? Promise.reject({
            response: { status: 401, data: { code: 40100, msg: '未认证', data: null } },
          })
        : Promise.resolve({
            data: { code: 0, msg: 'success', data: newSample },
            status: 200,
            statusText: 'OK',
            headers: {},
            config,
          });

    // The response interceptor clears credentials and dispatches AUTH_UNAUTHORIZED;
    // the base app must then re-register and show the new account.
    await expect(http.get('/v1/teams')).rejects.toBeTruthy();
    await flushPromises();
    await wrapper.vm.$nextTick();

    expect(wrapper.find('[data-testid="account-name"]').text()).toBe('user_new999');
    expect(wrapper.find('[data-testid="register-error-banner"]').exists()).toBe(false);
    expect(JSON.parse(localStorage.getItem('ai_design_account') as string)).toEqual(newSample);
    http.defaults.adapter = undefined;
  });
});
