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

/** 防抖时间（ms），流式场景避免每帧都重渲染 */
const DEBOUNCE_MS = 16;

/**
 * Markdown 渲染 composable。
 * 接收 rawText Ref<string>，输出渲染后的 HTML。
 * 流式场景做 16ms 防抖；对不完整 Markdown 做容错。
 */
export function useMarkdown(rawText: Ref<string>) {
  const renderedHtml = ref('');
  let timer: ReturnType<typeof setTimeout> | null = null;

  function render() {
    try {
      const result = markdown.parse(rawText.value) as string;
      renderedHtml.value = result;
    } catch {
      // 渲染失败时降级显示原始文本
      renderedHtml.value = escapeHtml(rawText.value);
    }
  }

  watch(
    rawText,
    () => {
      if (timer) clearTimeout(timer);
      timer = setTimeout(render, DEBOUNCE_MS);
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
