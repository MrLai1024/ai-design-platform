import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { prefixCss, installScopedCSSUpdateFix } from '../src/style-isolation-fix';

describe('prefixCss', () => {
  it('prefixes a single class selector', () => {
    const css = '.ant-btn { padding: 4px 15px; }';
    expect(prefixCss(css, 'div[data-qiankun="x"]')).toBe(
      'div[data-qiankun="x"] .ant-btn { padding: 4px 15px; }',
    );
  });

  it('prefixes each selector in a selector list', () => {
    const css = '.ant-btn, .ant-btn-primary { color: red; }';
    expect(prefixCss(css, 'P')).toBe('P .ant-btn, P .ant-btn-primary { color: red; }');
  });

  it('handles :where() and attribute selectors without breaking them', () => {
    const css = ':where(.hash)[class^="ant-btn"], :where(.hash)[class*=" ant-btn"] { box-sizing: border-box; }';
    expect(prefixCss(css, 'P')).toBe(
      'P :where(.hash)[class^="ant-btn"], P :where(.hash)[class*=" ant-btn"] { box-sizing: border-box; }',
    );
  });

  it('keeps @keyframes blocks untouched', () => {
    const css = '@keyframes antFadeIn { from { opacity: 0; } to { opacity: 1; } }';
    expect(prefixCss(css, 'P')).toBe(css);
  });

  it('recurses into @media blocks', () => {
    const css = '@media (max-width: 600px) { .ant-menu { display: none; } }';
    expect(prefixCss(css, 'P')).toBe('@media (max-width: 600px) { P .ant-menu { display: none; } }');
  });

  it('is idempotent when already prefixed', () => {
    const css = 'P .ant-btn { color: red; }';
    expect(prefixCss(css, 'P')).toBe(css);
  });

  it('replaces :root with the prefix', () => {
    expect(prefixCss(':root { --x: 1; }', 'P')).toBe('P { --x: 1; }');
  });
});

describe('installScopedCSSUpdateFix', () => {
  let disconnect: () => void;

  beforeEach(() => {
    document.body.innerHTML = '';
  });

  afterEach(() => {
    disconnect?.();
  });

  it('re-prefixes cssinjs style text updates (qiankun one-time rewrite gap)', async () => {
    const head = document.createElement('div');
    document.body.appendChild(head);
    const style = document.createElement('style');
    style.setAttribute('data-css-hash', 'abc');
    head.appendChild(style);
    style.innerHTML = 'P .ant-btn { color: red; }'; // initial state: qiankun already prefixed

    disconnect = installScopedCSSUpdateFix(head, 'P');

    // cssinjs later rewrites the text with unprefixed rules — the update must
    // be re-prefixed, otherwise prefixed base resets outrank the component css
    style.innerHTML = '.ant-btn { padding: 4px 15px; }';
    await new Promise((r) => setTimeout(r, 20));

    expect(style.innerHTML).toBe('P .ant-btn { padding: 4px 15px; }');
  });

  it('ignores mutations on unrelated elements', async () => {
    const head = document.createElement('div');
    document.body.appendChild(head);
    const other = document.createElement('style');
    head.appendChild(other);
    other.innerHTML = '.x { color: red; }';

    disconnect = installScopedCSSUpdateFix(head, 'P');

    other.innerHTML = '.x { color: blue; }';
    await new Promise((r) => setTimeout(r, 20));

    expect(other.innerHTML).toBe('.x { color: blue; }');
  });
});
