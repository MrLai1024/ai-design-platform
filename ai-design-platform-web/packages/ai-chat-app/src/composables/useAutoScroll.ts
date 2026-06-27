import { watch, ref, nextTick, type Ref } from 'vue';

const SCROLL_THRESHOLD = 80;

/**
 * 自动滚动 composable。
 * 流式输出 / 新消息时自动滚到底部，用户手动上滚时暂停，
 * 滚回底部时恢复。
 */
export function useAutoScroll(
  containerRef: Ref<HTMLElement | null>,
  deps: Ref<unknown>,
) {
  const isUserScrolling = ref(false);

  function scrollToBottom() {
    nextTick(() => {
      const el = containerRef.value;
      if (el && !isUserScrolling.value) {
        el.scrollTop = el.scrollHeight;
      }
    });
  }

  function onScroll() {
    const el = containerRef.value;
    if (!el) return;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    isUserScrolling.value = distanceFromBottom > SCROLL_THRESHOLD;
  }

  function forceScrollToBottom() {
    isUserScrolling.value = false;
    scrollToBottom();
  }

  watch(deps, () => {
    scrollToBottom();
  }, { deep: true });

  return {
    onScroll,
    scrollToBottom,
    forceScrollToBottom,
  };
}
