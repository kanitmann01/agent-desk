import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

// The SPA's unit harness. Component tests run in jsdom; a test file can
// opt into the plain node environment with a `@vitest-environment node`
// comment (the token tests read files, they render nothing).
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    include: ['src/**/*.test.{ts,tsx}'],
  },
});
