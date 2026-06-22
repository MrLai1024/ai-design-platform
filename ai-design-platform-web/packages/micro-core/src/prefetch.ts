import { prefetchApps, type AppMetadata } from 'qiankun';

/**
 * Prefetch sub-app assets after base app is idle.
 * Call after qiankun start().
 */
export function doPrefetch(apps: AppMetadata[]): void {
  if (typeof requestIdleCallback === 'function') {
    requestIdleCallback(() => {
      prefetchApps(apps);
    });
  } else {
    setTimeout(() => {
      prefetchApps(apps);
    }, 3000);
  }
}
