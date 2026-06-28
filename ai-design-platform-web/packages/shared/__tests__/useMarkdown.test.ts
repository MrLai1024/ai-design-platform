import { describe, it, expect } from 'vitest';
import { ref, nextTick } from 'vue';
import { useMarkdown } from '../src/composables/useMarkdown';

describe('useMarkdown', () => {
  it('should render plain text as paragraph', async () => {
    const input = ref('hello world');
    const { renderedHtml } = useMarkdown(input);
    await nextTick();
    await new Promise((r) => setTimeout(r, 20)); // wait for debounce
    expect(renderedHtml.value).toContain('hello world');
  });

  it('should render bold markdown', async () => {
    const input = ref('**bold text**');
    const { renderedHtml } = useMarkdown(input);
    await nextTick();
    await new Promise((r) => setTimeout(r, 20));
    expect(renderedHtml.value).toContain('<strong>bold text</strong>');
  });

  it('should render code blocks with language class', async () => {
    const input = ref('```typescript\nconst x = 1;\n```');
    const { renderedHtml } = useMarkdown(input);
    await nextTick();
    await new Promise((r) => setTimeout(r, 20));
    expect(renderedHtml.value).toContain('const x = 1');
    expect(renderedHtml.value).toContain('language-typescript');
  });

  it('should handle incomplete markdown gracefully', async () => {
    const input = ref('**unclosed bold');
    const { renderedHtml } = useMarkdown(input);
    await nextTick();
    await new Promise((r) => setTimeout(r, 20));
    // Should not throw, should contain original text
    expect(renderedHtml.value).toBeTruthy();
  });

  it('should sanitize XSS attempts', async () => {
    const input = ref('<script>alert("xss")</script>');
    const { renderedHtml } = useMarkdown(input);
    await nextTick();
    await new Promise((r) => setTimeout(r, 20));
    expect(renderedHtml.value).not.toContain('<script>');
  });
});
