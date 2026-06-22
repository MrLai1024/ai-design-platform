import { describe, it, expect } from 'vitest';
import { getAppConfigs, type AppConfig } from '../src/apps-config';

describe('getAppConfigs', () => {
  it('should return configs for all three sub-apps', () => {
    const configs = getAppConfigs();
    expect(configs).toHaveLength(3);

    const names = configs.map((c) => c.name);
    expect(names).toContain('ai-chat-app');
    expect(names).toContain('ai-generation-app');
    expect(names).toContain('ai-workflow');
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
    expect(new Set(containers).size).toBe(3);
  });
});
