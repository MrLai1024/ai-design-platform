import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import path from 'path'

export default defineConfig({
  plugins: [vue()],
  test: {
    environment: 'happy-dom',
    include: ['src/**/*.test.ts', '__tests__/**/*.test.ts'],
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
      '@ai-design/shared': path.resolve(__dirname, '../../shared/src'),
      '@ai-design/micro-core': path.resolve(__dirname, '../../micro-core/src'),
    },
  },
})
