import type { FrameworkLifeCycles } from 'qiankun';

/**
 * Global lifecycle hooks — called for every sub-app load/unmount cycle.
 * Use for global loading indicators, error reporting, etc.
 */
export function getGlobalLifecycleHooks(): FrameworkLifeCycles<Record<string, unknown>> {
  return {
    beforeLoad: async (app) => {
      console.log(`[micro-core] Loading ${app.name}...`);
    },

    beforeMount: async (app) => {
      console.log(`[micro-core] Mounting ${app.name}...`);
    },

    afterMount: async (app) => {
      console.log(`[micro-core] ${app.name} mounted`);
    },

    beforeUnmount: async (app) => {
      console.log(`[micro-core] Unmounting ${app.name}...`);
    },

    afterUnmount: async (app) => {
      console.log(`[micro-core] ${app.name} unmounted`);
    },
  };
}
