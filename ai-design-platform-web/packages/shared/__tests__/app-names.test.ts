import { describe, expect, it } from 'vitest';
import { APP_NAMES, APP_ROUTES } from '../src/constants/app-names';

describe('APP_NAMES', () => {
  it('defines PROJECT_SPACE as project-space-app', () => {
    expect(APP_NAMES.PROJECT_SPACE).toBe('project-space-app');
  });
});

describe('APP_ROUTES', () => {
  it('maps PROJECT_SPACE to /project-space', () => {
    expect(APP_ROUTES[APP_NAMES.PROJECT_SPACE]).toBe('/project-space');
  });

  it('keeps existing sub-app routes unchanged', () => {
    expect(APP_ROUTES[APP_NAMES.AI_CHAT]).toBe('/ai-chat');
    expect(APP_ROUTES[APP_NAMES.AI_GENERATION]).toBe('/ai-generation');
    expect(APP_ROUTES[APP_NAMES.AI_WORKFLOW]).toBe('/ai-workflow');
  });
});
