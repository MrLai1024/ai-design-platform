import {
  registerMicroApps,
  start,
  type RegistrableApp,
  type FrameworkConfiguration,
} from 'qiankun';
import type { AppConfig } from './apps-config';
import { getGlobalLifecycleHooks } from './lifecycle';
import { initCommunication } from './communication';
import { doPrefetch } from './prefetch';

let started = false;

/**
 * Register all sub-apps and start qiankun.
 * Should be called once from the base app after Vue/React app is mounted.
 */
export function setupMicroApps(apps: AppConfig[], startOpts?: FrameworkConfiguration): void {
  if (started) return;

  // Init global state communication
  initCommunication();

  // Transform our config to qiankun's format
  const microApps: RegistrableApp<Record<string, unknown>>[] = apps.map((app) => ({
    name: app.name,
    entry: app.entry,
    container: app.container,
    activeRule: app.activeRule,
    props: app.props || {},
  }));

  // Register
  registerMicroApps(microApps, getGlobalLifecycleHooks());

  // Start
  start({
    prefetch: false, // We handle prefetch separately
    sandbox: {
      experimentalStyleIsolation: true,
    },
    ...startOpts,
  });

  // Trigger prefetch after start
  doPrefetch(apps.map((a) => ({ name: a.name, entry: a.entry })));

  started = true;
}
