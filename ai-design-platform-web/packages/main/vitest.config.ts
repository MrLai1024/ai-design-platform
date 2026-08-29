import { defineConfig } from 'vitest/config';
import { resolve } from 'path';
import vue from '@vitejs/plugin-vue';

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
      '@ai-design/shared': resolve(__dirname, '../shared/src'),
      '@ai-design/shared/*': resolve(__dirname, '../shared/src/*'),
      '@ai-design/micro-core': resolve(__dirname, '../micro-core/src'),
      '@ai-design/micro-core/*': resolve(__dirname, '../micro-core/src/*'),
    },
  },
  test: {
    environment: 'happy-dom',
    include: ['__tests__/**/*.test.ts'],
  },
});
