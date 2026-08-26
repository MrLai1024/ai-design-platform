import { DOMWrapper } from '@vue/test-utils';

/**
 * antd-vue Modal teleports its DOM into document.body (Portal), outside the
 * mounted wrapper. These helpers query the body directly; call
 * `cleanupAntdModals` in afterEach to drop leaked portal roots.
 */

export function cleanupAntdModals(): void {
  document.querySelectorAll('.ant-modal-root').forEach((node) => node.remove());
}

export function bodyQuery(selector: string): DOMWrapper<Element> {
  const el = document.body.querySelector(selector);
  if (!el) {
    throw new Error(`No element matching "${selector}" found in document.body`);
  }
  return new DOMWrapper(el as Element);
}

export function bodyQueryAll(selector: string): DOMWrapper<Element>[] {
  return Array.from(document.body.querySelectorAll(selector)).map(
    (el) => new DOMWrapper(el as Element),
  );
}

/** antd inserts a space between two CJK chars in buttons ("创 建") */
export function findBodyButton(text: string): DOMWrapper<Element> {
  const button = bodyQueryAll('button').find((b) =>
    b.text().replace(/\s/g, '').includes(text.replace(/\s/g, '')),
  );
  if (!button) {
    throw new Error(`No button containing "${text}" found in document.body`);
  }
  return button;
}

/**
 * antd Form renders validation error text ~10ms after errors update
 * (FormItem's useDebounce is a setTimeout macrotask, which flushPromises
 * does not cover) — wait it out before asserting on error messages.
 */
export async function flushAntdFormDebounce(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, 30));
}
