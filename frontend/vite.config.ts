import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

// The build lands straight into the served static folder and is committed:
// the Python launcher serves it with zero node involvement. base matches
// the server's /static/spa/ mount so every emitted asset URL is
// self-hosted under the strict CSP.
export default defineConfig({
  base: '/static/spa/',
  plugins: [react(), tailwindcss()],
  build: {
    outDir: '../src/agentdesk/server/static/spa',
    emptyOutDir: true,
    sourcemap: false,
  },
});
