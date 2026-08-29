/**
 * Node 测试环境没有 requestAnimationFrame —— useMarkdown 用 rAF 做流式渲染节流
 * （每帧渲染最新累积内容，避免被连续 token 无限推迟）。
 * 这里用 setTimeout 模拟（约 16ms/帧），让 rAF 回调在宏任务队列中按序执行，
 * 与 happy-dom / 浏览器环境的时序兼容。
 */

function polyfillRequestAnimationFrame(): void {
  const raf = (callback: (time: number) => void): number =>
    setTimeout(() => callback(Date.now()), 16);

  const globalScope = globalThis as Record<string, unknown>;
  globalScope.requestAnimationFrame = raf;
  globalScope.cancelAnimationFrame = (id: number) => clearTimeout(id);
}

polyfillRequestAnimationFrame();
