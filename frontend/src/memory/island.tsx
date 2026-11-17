// The Memory page island: the server-rendered memory pages mount the
// graph into #memory-graph-root. The page already set the theme
// (theme-boot.js) and ships the shared tokens (/static/app.css).
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import MemoryGraph from './MemoryGraph';
import './memory-graph.css';

const root = document.getElementById('memory-graph-root');
if (root) {
  const endpoint = root.dataset.endpoint || '/api/memory/graph';
  const mode = root.dataset.mode === 'full' ? 'full' : 'page';
  createRoot(root).render(
    <StrictMode>
      <MemoryGraph endpoint={endpoint} mode={mode} />
    </StrictMode>,
  );
}
