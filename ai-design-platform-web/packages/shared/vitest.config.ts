import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    // Keep the default node environment — the suite is pure logic tests.
    // Only the rAF polyfill setup below is added for useMarkdown.
    environment: 'node',
    include: ['__tests__/**/*.test.ts'],
    setupFiles: ['./__tests__/setup.ts'],
  },
});
