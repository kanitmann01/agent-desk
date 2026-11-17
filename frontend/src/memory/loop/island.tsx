// The Memory page island: /memory mounts the whole page into
// #memory-loop-root. The server-rendered forms inside the root are the
// no-JavaScript fallback; React replaces them on mount. The page already
// set the theme (theme-boot.js) and ships the shared tokens.
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import MemoryLoop from './MemoryLoop';
import '../memory-graph.css';
import './memory-loop.css';

const root = document.getElementById('memory-loop-root');
if (root) {
  const endpoint = root.dataset.endpoint || '/api/memory/loop';
  createRoot(root).render(
    <StrictMode>
      <MemoryLoop endpoint={endpoint} />
    </StrictMode>,
  );
}
