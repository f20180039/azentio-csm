/// <reference types="vitest" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // One-laptop demo behind a tunnel: the panel calls /api and /sim on its own origin, so a teammate's browser
    // reaches the API and simulator on this laptop through the single tunnel URL (run with VITE_API_BASE=/api/v1
    // VITE_SIMULATOR_BASE=/sim/v1). Unused when the VITE_* bases point straight at the services.
    proxy: {
      '/api': { target: 'http://127.0.0.1:8080', changeOrigin: true },
      '/sim': { target: 'http://127.0.0.1:8090', changeOrigin: true, rewrite: (path) => path.replace(/^\/sim/, '') },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test-setup.ts'],
  },
});
