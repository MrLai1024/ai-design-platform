import type { FrameworkLifeCycles } from 'qiankun';

/**
 * Global lifecycle hooks — called for every sub-app load/unmount cycle.
 * Use for global loading indicators, error reporting, etc.
 */
export function getGlobalLifecycleHooks(): FrameworkLifeCycles<Record<string, unknown>> {
  return {
    beforeLoad: async () => {
      // no-op: 静默
    },

    beforeMount: async () => {
      // no-op: 静默
    },

    afterMount: async () => {
      // no-op: 静默
    },

    beforeUnmount: async () => {
      // no-op: 静默
    },

    afterUnmount: async () => {
      // no-op: 静默
    },
  };
}
