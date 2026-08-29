import { PATHS } from '../router/paths';

/**
 * Side menu entries — keys are top-level route paths derived from PATHS so
 * menu selection always matches the route config.
 */
export const SIDE_MENU_ITEMS = [
  { key: PATHS.PERSONAL, label: '个人项目' },
  { key: PATHS.TEAMS, label: '团队项目' },
] as const;
