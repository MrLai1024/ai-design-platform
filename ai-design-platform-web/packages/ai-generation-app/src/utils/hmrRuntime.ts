// hmrRuntime.ts — 注入到 PreviewFrame iframe 中的 HMR runtime
// 此文件编译为字符串，通过 srcdoc 注入到 iframe

export function generateHmrRuntimeScript(): string {
  return `
<script>
(function() {
  'use strict';

  // ── ModuleRegistry ──
  const modules = new Map();   // path -> { compiled, deps[], hot }

  function registerModule(path, compiled, deps) {
    modules.set(path, { compiled, deps: deps || [], hot: true });
  }

  function getModule(path) {
    return modules.get(path);
  }

  function getDependents(path) {
    const result = [];
    for (const [p, m] of modules) {
      if (m.deps.includes(path)) result.push(p);
    }
    return result;
  }

  // ── HotReloader ──
  function hotReplace(path, newCompiled) {
    const old = modules.get(path);
    if (!old) {
      // New module — just register
      registerModule(path, newCompiled, []);
      return { type: 'hot-replace', file: path };
    }

    // Update module
    modules.set(path, { ...old, compiled: newCompiled, hot: true });

    // Re-render dependents
    const dependents = getDependents(path);
    if (dependents.length > 0) {
      for (const dep of dependents) {
        const m = modules.get(dep);
        if (m && m.compiled && typeof m.compiled.rerender === 'function') {
          try {
            m.compiled.rerender();
          } catch {
            // 静默忽略
          }
        }
      }
    }

    return { type: 'hot-replace', file: path, dependents };
  }

  function warmReload(path, newCompiled) {
    registerModule(path, newCompiled, []);
    // Trigger full re-render of dependents
    const dependents = getDependents(path);
    for (const dep of dependents) {
      const m = modules.get(dep);
      if (m && m.compiled && typeof m.compiled.rerender === 'function') {
        try { m.compiled.rerender(); } catch(e) {}
      }
    }
    return { type: 'warm-reload', file: path, dependents };
  }

  // ── IncrementalCompiler ──
  function onFileUpdate(path, code, isLastChunk) {
    try {
      const exports = {};
      const fn = new Function('exports', 'require', code);
      fn(exports, function fakeRequire(p) { return modules.get(p)?.compiled; });
      const compiled = exports.default || exports;

      if (isLastChunk) {
        const old = modules.get(path);
        if (old) {
          return hotReplace(path, compiled);
        } else {
          registerModule(path, compiled, []);
          return { type: 'full-reload', file: path };
        }
      }
      return { type: 'chunk-accumulated', file: path };
    } catch(e) {
      if (e instanceof SyntaxError) {
        return { type: 'compile-error', file: path, error: e.message, recoverable: true };
      }
      return { type: 'compile-error', file: path, error: e.message, recoverable: false };
    }
  }

  // ── Message handlers ──
  window.addEventListener('message', function(e) {
    if (!e.data || !e.data.type) return;

    switch(e.data.type) {
      case 'hmr-file-chunk':
        const result = onFileUpdate(e.data.path, e.data.code, e.data.isLast);
        window.parent.postMessage({ type: 'hmr-result', ...result }, '*');
        break;

      case 'hmr-css-update':
        let styleEl = document.getElementById('hmr-style-' + e.data.path.replace(/[^a-z0-9]/gi, '-'));
        if (!styleEl) {
          styleEl = document.createElement('style');
          styleEl.id = 'hmr-style-' + e.data.path.replace(/[^a-z0-9]/gi, '-');
          document.head.appendChild(styleEl);
        }
        styleEl.textContent = e.data.css;
        window.parent.postMessage({ type: 'hmr-result', type2: 'hot-replace', file: e.data.path, css: true }, '*');
        break;

      case 'hmr-full-reload':
        window.location.reload();
        break;
    }
  });

  // Signal ready
  window.parent.postMessage({ type: 'hmr-ready' }, '*');
})();
<\/script>`;
}
