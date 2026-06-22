export { getAppConfigs } from './apps-config';
export type { AppConfig } from './apps-config';
export { setupMicroApps } from './register';
export { getGlobalLifecycleHooks } from './lifecycle';
export {
  initCommunication,
  onGlobalStateChange,
  setGlobalState,
  offGlobalStateChange,
} from './communication';
export { doPrefetch } from './prefetch';
