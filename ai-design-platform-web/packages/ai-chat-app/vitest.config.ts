import { defineConfig } from 'vitest/config';
import { resolve } from 'path';

export default defineConfig({
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
      '@ai-design/shared': resolve(__dirname, '../shared/src'),
      '@ai-design/micro-core': resolve(__dirname, '../micro-core/src'),
    },
  },
  test: {
    environment: 'happy-dom',
    include: ['__tests__/**/*.test.ts'],
  },
});
