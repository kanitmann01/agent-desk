import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = fileURLToPath(new URL('.', import.meta.url));

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
  // Every rail page: the consolidation surfaces and the plugins page are
  // server-rendered too, so their tabs must not fall back to this dev
  // shell. Pinned against the rail link set by src/test/devproxy.test.ts.
  '/plugins', '/activity', '/memory', '/mail', '/capabilities', '/peers',
  '/agents',
  // The SPA's own widget calls (the commitments check) also go to the
  // Python server, not to this dev origin.
  '/widgets',
];

export default defineConfig({
  base: '/static/spa/',
  plugins: [react()],
  server: {
    // 5173 is commonly taken (vite then drifts to another port and every
    // printed hint lies). Pin an uncommon port and fail loudly instead.
    port: 5199,
    strictPort: true,
    proxy: Object.fromEntries(
      backendPaths.map((path) => [
        path,
        {
          target: BACKEND,
          // The server's Origin/Host guard is right to block a foreign
          // origin, so the proxy speaks to it exactly as a production
          // browser would: backend Host, matching Origin and Referer.
          changeOrigin: true,
          configure(proxy) {
            proxy.on('proxyReq', (req) => {
              req.setHeader('origin', BACKEND);
              req.setHeader('referer', BACKEND + '/');
            });
          },
        },
      ]),
    ),
  },
  build: {
    outDir: '../src/nexuusbot/server/static/spa',
    emptyOutDir: true,
    sourcemap: false,
    // The CSP allows fonts from 'self' only, so no font may travel as a
    // data: URL (vite inlines small assets by default).
    assetsInlineLimit: 0,
    // Three entries: the SPA shell, the Memory page, and the graph island the
    // server-rendered memory pages load by a fixed name
    // (assets/memory-graph.js and .css), so the Python side never has
    // to read a manifest to find it.
    rollupOptions: {
      input: {
        index: resolve(here, 'index.html'),
        'memory-graph': resolve(here, 'src/memory/island.tsx'),
        // The Memory page itself (capture, review, knowledge, removal),
        // mounted into /memory by the same fixed-name rule.
        'memory-loop': resolve(here, 'src/memory/loop/island.tsx'),
      },
      output: {
        entryFileNames: (chunk) =>
          chunk.name === 'memory-graph' || chunk.name === 'memory-loop'
            ? `assets/${chunk.name}.js`
            : 'assets/[name]-[hash].js',
        assetFileNames: (asset) => {
          const names = asset.names ?? [];
          // The page entry also pulls in the graph's stylesheet, so its
          // bundle carries both names: match it first.
          if (names.includes('memory-loop.css')) return 'assets/memory-loop.css';
          if (names.includes('memory-graph.css')) return 'assets/memory-graph.css';
          return 'assets/[name]-[hash][extname]';
        },
      },
    },
  },
});
