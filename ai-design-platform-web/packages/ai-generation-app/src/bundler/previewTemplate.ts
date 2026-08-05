// src/bundler/previewTemplate.ts
// 预览 iframe 文档模板：import map 外置依赖 + ES module 内联 bundle + CSS 注入 + 错误回传。

export interface PreviewDocOptions {
  /** 打包产出的 ES module JS（内联注入） */
  js: string
  /** 收集的 CSS（SFC style + .css 文件） */
  css: string
  /** 额外组件库 CDN（复用现有 getConfig().cdnUrls） */
  cdnUrls?: string[]
}

/**
 * 注入预览 iframe 的运行时错误捕获脚本（5.4 L3 证据源）。
 *
 * 捕获四类错误并以 postMessage 结构化回传父窗口：
 * - console.error（wrap 保留原始行为）
 * - window error 事件（uncaught）
 * - unhandledrejection（未处理 Promise 拒绝）
 * - fetch / XMLHttpRequest 失败（network；abort 不报 —— 用户主动取消
 *   不是应用错误，会污染 L3 证据）
 *
 * 防环：同 (type, message) 1 秒内去重；脚本自身 try/catch 兜底。
 * 父窗口收到 {type: 'runtime-error', errors: [...]} 后批量 POST 到
 * /api/v1/generation/runtime-feedback（Verifier L3 证据）。
 */
export const RUNTIME_CAPTURE_SCRIPT = `(function () {
  if (window.__aiRuntimeCaptureInstalled) return;
  window.__aiRuntimeCaptureInstalled = true;
  function post(errors) {
    try { window.parent.postMessage({ type: 'runtime-error', errors: errors }, '*'); } catch (e) { /* ignore */ }
  }
  function strip(s) { return String(s == null ? '' : s); }
  var lastKey = null, lastTs = 0;
  function dedupe(type, message) {
    var now = Date.now();
    var key = type + '|' + message;
    if (key === lastKey && now - lastTs < 1000) return true;
    lastKey = key; lastTs = now;
    return false;
  }
  function emit(type, message, stack, url) {
    if (dedupe(type, message)) return;
    var err = { type: type, message: strip(message).slice(0, 500) };
    if (stack) err.stack = strip(stack).slice(0, 1000);
    if (url) err.url = strip(url).slice(0, 500);
    post([err]);
  }
  window.addEventListener('error', function (e) {
    emit('uncaught', e.message || 'Unknown error', e.error && e.error.stack, e.filename || '');
  }, true);
  window.addEventListener('unhandledrejection', function (e) {
    var r = e.reason || {};
    emit('unhandledrejection', (r && r.message) || strip(r), r && r.stack, '');
  });
  var origError = window.console && console.error.bind(console);
  if (origError) {
    console.error = function () {
      try { origError.apply(console, arguments); } catch (e) { /* ignore */ }
      var parts = [];
      for (var i = 0; i < arguments.length; i++) {
        var a = arguments[i];
        parts.push(a instanceof Error ? (a.message || String(a)) : strip(a));
      }
      emit('console_error', parts.join(' '));
    };
  }
  var origFetch = window.fetch;
  if (origFetch) {
    window.fetch = function (input, init) {
      return origFetch.apply(this, arguments).catch(function (err) {
        var url = typeof input === 'string' ? input : (input && input.url) || '';
        emit('network', 'fetch failed: ' + ((err && err.message) || err) + (url ? ' (' + url + ')' : ''), '', url);
        throw err;
      });
    };
  }
  var origOpen = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function (method, url) {
    // 只监听 error（abort 是用户主动取消，不算应用错误 —— L3 证据去噪）
    this.addEventListener('error', function () {
      emit('network', 'xhr failed: ' + method + ' ' + url, '', String(url));
    });
    return origOpen.apply(this, arguments);
  };
})();`

const IMPORT_MAP = {
  imports: {
    vue: 'https://esm.sh/vue@3.4.38',
    'vue-router': 'https://esm.sh/vue-router@4.4.3',
    pinia: 'https://esm.sh/pinia@2.2.2',
  },
}

export function buildPreviewDoc(opts: PreviewDocOptions): string {
  const { js, css, cdnUrls = [] } = opts

  const cdnTags = cdnUrls
    .map((url) => (url.endsWith('.css') ? `<link rel="stylesheet" href="${url}">` : `<script src="${url}"><\/script>`))
    .join('\n')

  // 内联 bundle —— 注意转义 </script> 防止文档提前闭合
  const safeJs = js.replace(/<\/script>/gi, '<\\/script>')

  return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <script type="importmap">${JSON.stringify(IMPORT_MAP)}<\/script>
  ${cdnTags}
  <style>
    *, *::before, *::after { box-sizing: border-box; }
    body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
  </style>
  <style id="__bundled_css__">${css}</style>
</head>
<body>
  <div id="app"></div>
  <script>
    window.onerror = function(msg, url, line, col, error) {
      window.parent.postMessage({
        type: 'err',
        message: 'Runtime: ' + msg + (line ? ' at line ' + line : '')
      }, '*');
    };
    window.addEventListener('unhandledrejection', function(e) {
      window.parent.postMessage({
        type: 'err',
        message: 'Async: ' + (e.reason && e.reason.message ? e.reason.message : String(e.reason))
      }, '*');
    });
    ${RUNTIME_CAPTURE_SCRIPT}
  <\/script>
  <script type="module">
    ${safeJs}
    window.parent.postMessage({ type: 'ready' }, '*');
  <\/script>
</body>
</html>`
}
