/// <reference types="vitest" />
import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';

/** Secret the panel's proxy adds to every voice request so the voice service's tunnel guard admits it. */
const VOICE_PROXY_TOKEN_VAR = 'VOICE_PROXY_TOKEN';
const VOICE_PROXY_TOKEN_HEADER = 'x-voice-proxy-token';
/** Same minimum as PROXY_TOKEN_MIN_CHARS in backend/voice/app/config.py: a shorter token is ignored there, so it is not sent. */
const VOICE_PROXY_TOKEN_MIN_CHARS = 32;
const VOICE_PROXY_ENV_PREFIX = 'VOICE_PROXY'; // only VOICE_PROXY_* is read from the repo-root .env, nothing else in it
const VOICE_TARGET_VAR = 'VOICE_PROXY_TARGET';
const SHARE_VOICE_BASE = '/voice'; // VITE_VOICE_BASE in share mode (npm run dev:share): voice requests go through this proxy
const REPO_ROOT = fileURLToPath(new URL('..', import.meta.url));

/** The token to send, or '' when it is missing or too short (share mode then warns, naming no value, and fails closed). */
export function proxyToken(raw: string | undefined, shareMode: boolean, warn: (message: string) => void = console.warn): string {
  const token = raw?.trim() ?? '';
  if (token.length >= VOICE_PROXY_TOKEN_MIN_CHARS) return token;
  if (shareMode) {
    warn(
      `[dev:share] ${VOICE_PROXY_TOKEN_VAR} is ${token ? `shorter than ${VOICE_PROXY_TOKEN_MIN_CHARS} characters` : 'missing'}: ` +
        'the voice service will answer 403 LOCAL_ONLY through the tunnel. Set it in the repo-root .env and restart the voice service.',
    );
  }
  return '';
}

export default defineConfig(({ mode }) => {
  // The repo-root .env is what the voice service reads too; only its VOICE_PROXY_* keys are loaded, on the server
  // only: nothing from it is exposed to client code (that still needs the VITE_ prefix).
  const env = { ...loadEnv(mode, REPO_ROOT, VOICE_PROXY_ENV_PREFIX), ...process.env };
  const token = proxyToken(env[VOICE_PROXY_TOKEN_VAR], env.VITE_VOICE_BASE === SHARE_VOICE_BASE);
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
