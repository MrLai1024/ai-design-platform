import { describe, it, expect } from 'vitest';
import { getAppConfigs, type AppConfig } from '../src/apps-config';

describe('getAppConfigs', () => {
  it('should return configs for both sub-apps', () => {
    const configs = getAppConfigs();
    expect(configs).toHaveLength(2);

    const names = configs.map((c) => c.name);
    expect(names).toContain('ai-generation-app');
    expect(names).toContain('project-space-app');
  });

  it('registers project-space-app with its container, activeRule and entry', () => {
    const configs = getAppConfigs();
    const cfg = configs.find((c) => c.name === 'project-space-app');
    expect(cfg).toBeDefined();

    expect(cfg!.container).toBe('#sub-app-project-space');
    expect(cfg!.activeRule).toBe('/project-space');
    // Dev serves from :8004, prod from the CDN — both must reference project-space-app
    expect(cfg!.entry).toMatch(/localhost:8004|cdn\.example\.com\/project-space-app/);
  });

  it('should have required fields on each config', () => {
    const configs = getAppConfigs();
    for (const cfg of configs) {
      expect(cfg).toHaveProperty('name');
      expect(cfg).toHaveProperty('entry');
      expect(cfg).toHaveProperty('container');
      expect(cfg).toHaveProperty('activeRule');
    }
  });

  it('should use unique containers per app', () => {
    const configs = getAppConfigs();
    const containers = configs.map((c) => c.container);
    expect(new Set(containers).size).toBe(2);
  });
});
