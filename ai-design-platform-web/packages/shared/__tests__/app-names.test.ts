import { describe, expect, it } from 'vitest';
import { APP_NAMES, APP_ROUTES } from '../src/constants/app-names';

describe('APP_NAMES', () => {
  it('defines MAIN as main', () => {
    expect(APP_NAMES.MAIN).toBe('main');
  });

  it('defines AI_GENERATION as ai-generation-app', () => {
    expect(APP_NAMES.AI_GENERATION).toBe('ai-generation-app');
  });

  it('defines PROJECT_SPACE as project-space-app', () => {
    expect(APP_NAMES.PROJECT_SPACE).toBe('project-space-app');
  });
});

describe('APP_ROUTES', () => {
  it('maps AI_GENERATION to /ai-generation', () => {
    expect(APP_ROUTES[APP_NAMES.AI_GENERATION]).toBe('/ai-generation');
  });

  it('maps PROJECT_SPACE to /project-space', () => {
    expect(APP_ROUTES[APP_NAMES.PROJECT_SPACE]).toBe('/project-space');
  });
});
