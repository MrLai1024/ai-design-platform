// src/utils/buildPreviewHtml.ts

/**
 * 构建注入 iframe srcdoc 的完整 HTML 文档。
 * 包含 Vue runtime、组件库 CDN、编译产物、错误边界。
 */
export function buildPreviewHtml(
  compiledCode: string,
  compiledCSS: string,
  cdnUrls: string[],
): string {
  const cdnTags = cdnUrls
    .map((url) => {
      if (url.endsWith('.css')) return `<link rel="stylesheet" href="${url}">`
      return `<script src="${url}"><\/script>`
    })
    .join('\n')

  return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <script src="https://unpkg.com/vue@3/dist/vue.global.prod.js"><\/script>
  ${cdnTags}
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
    ${compiledCSS}
  </style>
</head>
<body>
  <div id="app"></div>
  <script>
    (function() {
      var __VUE__ = Vue;
      var __DEPS__ = {};
      var components = {};

      function mountComponent(code) {
        try {
          var fn = new Function('__VUE__', '__DEPS__', code);
          var component = fn(__VUE__, __DEPS__);
          var app = Vue.createApp(component);
          app.mount('#app');
        } catch (e) {
          window.parent.postMessage({ type: 'err', message: 'Mount error: ' + e.message }, '*');
        }
      }

      ${compiledCode ? `mountComponent(${JSON.stringify(compiledCode)});` : '// no compiled code'}
    })();
  <\/script>
  <script>
    window.onerror = function(msg, url, line, col, error) {
      window.parent.postMessage({
        type: 'err',
        message: 'Runtime: ' + msg + ' at line ' + line
      }, '*');
    };
    window.parent.postMessage({ type: 'ready' }, '*');
  <\/script>
</body>
</html>`
}
