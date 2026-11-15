import { loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

function port(value: string | undefined, fallback: number): number {
  const result = Number(value || fallback);
  if (!Number.isInteger(result) || result < 1 || result > 65535) {
    throw new Error('Admin 端口必须为 1–65535 的整数。');
  }
  return result;
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const target = env.ADMIN_API_PROXY_TARGET || 'http://127.0.0.1:8000';
  const proxy = { '/api': { target, changeOrigin: true } };
  return {
    plugins: [react()],
    server: { host: '127.0.0.1', port: port(env.ADMIN_DEV_PORT, 5174), strictPort: true, proxy },
    preview: { host: '127.0.0.1', port: port(env.ADMIN_PREVIEW_PORT, 4174), strictPort: true, proxy },
    test: {
      environment: 'jsdom', setupFiles: ['./src/tests/setup.ts'], css: false,
      execArgv: ['--no-experimental-webstorage'],
      environmentOptions: { jsdom: { url: 'http://localhost:5174' } },
    },
  };
});
