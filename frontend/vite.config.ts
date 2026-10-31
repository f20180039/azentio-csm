/// <reference types="vitest" />
import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';

/** Secret the panel's proxy adds to every voice request so the voice service's tunnel guard admits it. */
const VOICE_PROXY_TOKEN_VAR = 'VOICE_PROXY_TOKEN';
const VOICE_PROXY_TOKEN_HEADER = 'x-voice-proxy-token';
const VOICE_TARGET_VAR = 'VOICE_PROXY_TARGET';
const REPO_ROOT = fileURLToPath(new URL('..', import.meta.url));

export default defineConfig(({ mode }) => {
  // The repo-root .env is what the voice service reads too. '' as the prefix loads every key here, on the server
  // only: nothing from it is exposed to client code (that still needs the VITE_ prefix).
  const env = { ...loadEnv(mode, REPO_ROOT, ''), ...process.env };
  const token = env[VOICE_PROXY_TOKEN_VAR]?.trim() ?? '';
  const voiceTarget = env[VOICE_TARGET_VAR] || 'http://127.0.0.1:7861';
  return {
    plugins: [react()],
    server: {
      port: 5173,
      // One-laptop demo behind a tunnel: the panel calls /api, /sim and /voice on its own origin, so a judge's browser
      // reaches the API, simulator and voice service on this laptop through the single tunnel URL (run with
      // npm run dev:share). Unused when the VITE_* bases point straight at the services.
      proxy: {
        '/api': { target: 'http://127.0.0.1:8080', changeOrigin: true },
        '/sim': { target: 'http://127.0.0.1:8090', changeOrigin: true, rewrite: (path) => path.replace(/^\/sim/, '') },
        // The voice service refuses tunnelled requests unless this proxy vouches for them with VOICE_PROXY_TOKEN from
        // .env; the header is added here, on the laptop, so the secret never reaches a browser. Without a token the
        // header is omitted and the voice service answers 403 LOCAL_ONLY through the tunnel, as before.
        '/voice': {
          target: voiceTarget,
          changeOrigin: true,
          ws: true,
          rewrite: (path) => path.replace(/^\/voice/, ''),
          ...(token ? { headers: { [VOICE_PROXY_TOKEN_HEADER]: token } } : {}),
        },
      },
    },
    test: {
      environment: 'jsdom',
      globals: true,
      setupFiles: ['./src/test-setup.ts'],
    },
  };
});
