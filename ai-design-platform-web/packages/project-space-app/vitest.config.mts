import { defineConfig } from 'vitest/config';
import { resolve } from 'path';
import vue from '@vitejs/plugin-vue';
import Components from 'unplugin-vue-components/vite';
import { AntDesignVueResolver } from 'unplugin-vue-components/resolvers';

export default defineConfig({
  plugins: [
    vue(),
    // Same on-demand antd-vue setup as the webpack build (v4 CSS-in-JS → no style imports)
    Components({
      resolvers: [AntDesignVueResolver({ importStyle: false })],
    }),
  ],
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
