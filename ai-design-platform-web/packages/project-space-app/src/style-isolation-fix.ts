/**
 * Workaround for qiankun scopedCSS vs antd-vue cssinjs updates.
 *
 * qiankun's experimentalStyleIsolation (= scopedCSS rewriting in qiankun
 * 2.10.16) rewrites the text of every style element ONCE, prefixing each
 * selector with `div[data-qiankun="..."]`. antd-vue's cssinjs, however,
 * updates existing style elements later (e.g. when a component using the
 * same style key mounts on another route): it compares the DOM text with its
 * own generated css, sees they differ (prefixed vs unprefixed), and rewrites
 * the element with UNPREFIXED rules.
 *
 * After that rewrite the cascade inverts: the app's own base resets are
 * still prefixed (`div[data-qiankun] button { ... }`, specificity 0-1-1) and
 * now outrank the unprefixed antd component rules (0-1-0), so buttons and
 * other re-registered components render unstyled until the next full page
 * load (fresh load = everything prefixed again).
 *
 * This module re-applies the prefix whenever a cssinjs style element's text
 * is mutated, restoring parity between the two. Only needed while qiankun's
 * style isolation is enabled for this app.
 */

const CSSINJS_STYLE_SELECTOR = 'style[data-css-hash]';

interface TopLevelRule {
  header: string;
  body: string;
  isBlock: boolean;
}

/** Split css text into top-level rules, keeping braces/brackets balanced. */
function splitTopLevelRules(css: string): TopLevelRule[] {
  const rules: TopLevelRule[] = [];
  let depth = 0;
  let buf = '';
  let i = 0;
  while (i < css.length) {
    const ch = css[i];
    if (ch === '{') {
      depth += 1;
      if (depth === 1) {
        const header = buf.trim();
        buf = '';
        i += 1;
        const bodyStart = i;
        while (i < css.length && depth > 0) {
          if (css[i] === '{') depth += 1;
          if (css[i] === '}') depth -= 1;
          if (depth > 0) i += 1;
        }
        rules.push({ header, body: css.slice(bodyStart, i), isBlock: true });
        i += 1;
        continue;
      }
    }
    if (ch === ';' && depth === 0) {
      rules.push({ header: buf.trim(), body: '', isBlock: false });
      buf = '';
      i += 1;
      continue;
    }
    buf += ch;
    i += 1;
  }
  if (buf.trim()) {
    rules.push({ header: buf.trim(), body: '', isBlock: false });
  }
  return rules;
}

/** Prefix a comma-separated selector list (commas inside brackets/parens ignored). */
function prefixSelectorList(selectors: string, prefix: string): string {
  const parts: string[] = [];
  let depth = 0;
  let buf = '';
  for (const ch of selectors) {
    if ((ch === ',' ) && depth === 0) {
      parts.push(buf.trim());
      buf = '';
      continue;
    }
    if (ch === '(' || ch === '[') depth += 1;
    if (ch === ')' || ch === ']') depth -= 1;
    buf += ch;
  }
  parts.push(buf.trim());
  return parts
    .map((s) => {
      if (s === ':root' || s === 'html' || s === 'body') return prefix;
      return `${prefix} ${s}`;
    })
    .join(', ');
}

/** Prefix all style rules in the given css text; @keyframes/@import/@font-face are kept. */
export function prefixCss(css: string, prefix: string): string {
  const out: string[] = [];
  for (const rule of splitTopLevelRules(css)) {
    if (!rule.isBlock) {
      out.push(rule.header);
      continue;
    }
    const atRule = /^@([\w-]+)/.exec(rule.header);
    if (atRule) {
      const kind = atRule[1].toLowerCase();
      if (kind === 'media' || kind === 'supports' || kind === 'container' || kind === 'layer') {
        out.push(`${rule.header} { ${prefixCss(rule.body, prefix).trim()} }`);
      } else {
        // @keyframes / @import / @font-face / @page — keep untouched
        out.push(`${rule.header} {${rule.body}}`);
      }
      continue;
    }
    if (rule.header.startsWith(prefix)) {
      out.push(`${rule.header} {${rule.body}}`);
      continue;
    }
    out.push(`${prefixSelectorList(rule.header, prefix)} {${rule.body}}`);
  }
  return out.join('');
}

/**
 * Observe the subtree containing qiankun-head (the app wrapper) and re-prefix
 * cssinjs style elements whenever their text is rewritten. Returns a
 * disconnect function.
 */
export function installScopedCSSUpdateFix(root: HTMLElement, prefix: string): () => void {
  const observer = new MutationObserver((mutations) => {
    const seen = new Set<HTMLStyleElement>();
    for (const mutation of mutations) {
      let target: Node | null = mutation.target;
      if (target.nodeType === Node.TEXT_NODE && target.parentElement) {
        target = target.parentElement;
      }
      const el = target instanceof HTMLStyleElement ? target : (target as Element).closest?.(CSSINJS_STYLE_SELECTOR);
      if (el instanceof HTMLStyleElement && el.matches(CSSINJS_STYLE_SELECTOR)) {
        seen.add(el);
      }
    }
    for (const el of seen) {
      const text = el.innerHTML;
      if (!text) continue;
      // avoid observer feedback loops: qiankun's own rewrite and this fix both
      // set the text; only rewrite when at least one rule lost the prefix
      if (!needsPrefix(text, prefix)) continue;
      el.innerHTML = prefixCss(text, prefix);
    }
  });
  observer.observe(root, { subtree: true, childList: true, characterData: true });
  return () => observer.disconnect();
}

function needsPrefix(css: string, prefix: string): boolean {
  for (const rule of splitTopLevelRules(css)) {
    if (!rule.isBlock) continue;
    if (/^@/.test(rule.header)) {
      if (/^@(media|supports|container|layer)/i.test(rule.header)) {
        if (needsPrefix(rule.body, prefix)) return true;
      }
      continue;
    }
    if (!rule.header.startsWith(prefix)) return true;
  }
  return false;
}
