import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import './index.css';
import { storedTheme, syncThemeColor } from './theme/theme';

// public/theme-boot.js set the theme before first paint; if it did not
// run, set it now. Then match the browser chrome to the canvas.
if (!document.documentElement.dataset.theme) {
  document.documentElement.dataset.theme = storedTheme();
}
syncThemeColor();

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
