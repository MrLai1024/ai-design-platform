/**
 * Holds the element the Vue app is mounted into.
 *
 * Under qiankun, `document.getElementById('app')` resolves to the BASE app's
 * root (first #app in document order) — NOT the sub-app root inside the
 * qiankun wrapper. Overlay components (antd Modal etc.) teleport to
 * document.body by default, which puts them outside the wrapper and therefore
 * outside the scope of qiankun's `div[data-qiankun="..."]`-prefixed rules
 * (experimentalStyleIsolation = scopedCSS rewriting). Rendering overlays into
 * the mounted root keeps them inside the wrapper so the prefixed rules apply.
 */
let appRoot: HTMLElement | null = null;

export function setAppRoot(el: HTMLElement): void {
  appRoot = el;
}

export function getAppRoot(): HTMLElement {
  return appRoot ?? document.body;
}
