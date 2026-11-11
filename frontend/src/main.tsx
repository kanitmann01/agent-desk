import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import Backdrop from './components/Backdrop';
import './index.css';

// The backdrop is decoration with no app state, and it must stay
// outside StrictMode (the reason is in Backdrop.tsx). Everything that
// holds data or talks to the server stays inside it.
createRoot(document.getElementById('root')!).render(
  <>
    <Backdrop />
    <StrictMode>
      <App />
    </StrictMode>
  </>,
);
