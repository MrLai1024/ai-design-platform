import { defineConfig } from 'vitest/config';
import path from 'path';

export default defineConfig({
  resolve: {
    alias: {
      '@ai-design/shared': path.resolve(__dirname, '../shared/src'),
    },
  },
});
