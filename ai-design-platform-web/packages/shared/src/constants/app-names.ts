/** Sub-app name constants — keep in sync with registerMicroApps config */
export const APP_NAMES = {
  MAIN: 'main',
  AI_CHAT: 'ai-chat-app',
  AI_GENERATION: 'ai-generation-app',
  AI_WORKFLOW: 'ai-workflow',
} as const;

/** Route path prefixes for each sub-app */
export const APP_ROUTES = {
  [APP_NAMES.AI_CHAT]: '/ai-chat',
  [APP_NAMES.AI_GENERATION]: '/ai-generation',
  [APP_NAMES.AI_WORKFLOW]: '/ai-workflow',
} as const;
