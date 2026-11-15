import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true, proxy: { '/api': 'http://127.0.0.1:8000' } },
  preview: { port: 4173, proxy: { '/api': 'http://127.0.0.1:8000' } },
  build: { rollupOptions: { output: { manualChunks(id) {
    if (id.includes('/zrender/')) return 'chart-renderer';
    if (id.includes('/echarts/')) return 'chart-engine';
  } } } },
  test: {
    environment: 'jsdom', setupFiles: ['./src/tests/setup.ts'], css: false,
    execArgv: ['--no-experimental-webstorage'],
    environmentOptions: { jsdom: { url: 'http://localhost:5173' } },
  },
});
