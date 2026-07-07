import { ref, watch, type Ref } from 'vue';
import { Marked } from 'marked';
import hljs from 'highlight.js';

// 配置 marked 实例（独立实例避免污染全局）
const markdown = new Marked({
  breaks: true,
  gfm: true,
});

// 对原始 HTML 做转义，防止 XSS
markdown.use({
  renderer: {
    html(token: { text: string }) {
      return token.text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
    },
  },
});

/**
 * Markdown 渲染 composable。
 * 接收 rawText Ref<string>，输出渲染后的 HTML。
 * 流式场景使用 requestAnimationFrame 做节流（而非防抖），
 * 保证每帧都能渲染最新的累积内容，不会被连续 token 无限推迟。
 * 对不完整 Markdown 做容错。
 */
export function useMarkdown(rawText: Ref<string>) {
  const renderedHtml = ref('');
  let rafId: number | null = null;
  let pendingRender = false;

  function render() {
    pendingRender = false;
    try {
      const result = markdown.parse(rawText.value) as string;
      renderedHtml.value = result;
    } catch {
      // 渲染失败时降级显示原始文本
      renderedHtml.value = escapeHtml(rawText.value);
    }
  }

  function scheduleRender() {
    if (!pendingRender) {
      pendingRender = true;
      rafId = requestAnimationFrame(() => {
        rafId = null;
        render();
      });
    }
  }

  watch(
    rawText,
    () => {
      scheduleRender();
    },
    { immediate: true },
  );

  return { renderedHtml };
}

/** 简单的 HTML 转义 */
function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
