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
  <\/script>
  <script type="module">
    ${safeJs}
    window.parent.postMessage({ type: 'ready' }, '*');
  <\/script>
</body>
</html>`
}
