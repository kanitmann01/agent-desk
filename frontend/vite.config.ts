import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

// The build lands straight into the served static folder and is committed:
// the Python launcher serves it with zero node involvement. base matches
// the server's /static/spa/ mount so every emitted asset URL is
// self-hosted under the strict CSP.
// Dev mode: every path the Python server answers is proxied to it, so
// the dev origin behaves like production (auth cookie included, because
// Set-Cookie passes through the proxy onto localhost). /static/spa is
// NOT listed: vite serves the live sources there itself.
const BACKEND = 'http://127.0.0.1:8765';
const backendPaths = [
  '/api', '/auth', '/sources', '/settings', '/research', '/assistant',
  '/inbox', '/skills', '/wizard', '/audit', '/health', '/walkthrough',
  '/what-this-touches', '/static/app',
];

export default defineConfig({
  base: '/static/spa/',
  plugins: [react(), tailwindcss()],
  server: {
    proxy: Object.fromEntries(
      backendPaths.map((path) => [path, { target: BACKEND, changeOrigin: false }]),
    ),
  },
  build: {
    outDir: '../src/agentdesk/server/static/spa',
    emptyOutDir: true,
    sourcemap: false,
  },
});
