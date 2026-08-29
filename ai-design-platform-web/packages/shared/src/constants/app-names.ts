/** Sub-app name constants — keep in sync with registerMicroApps config */
export const APP_NAMES = {
  MAIN: 'main',
  AI_GENERATION: 'ai-generation-app',
  PROJECT_SPACE: 'project-space-app',
} as const;

/** Route path prefixes for each sub-app */
export const APP_ROUTES = {
  [APP_NAMES.AI_GENERATION]: '/ai-generation',
  [APP_NAMES.PROJECT_SPACE]: '/project-space',
} as const;
