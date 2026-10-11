import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
// No webfont import: the console uses the platform font stack, the same choice
// ChatGPT makes. It removes two render-blocking requests from the critical path.
import '@/design/tokens.css';
import '@/design/base.css';
import { App } from '@/app/App';

const container = document.getElementById('root');
if (!container) throw new Error('Не найден корневой элемент #root');

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

// Installable shell; API and private conversations remain network-only.
if (import.meta.env.PROD && 'serviceWorker' in navigator) {
  window.addEventListener('load', () => { void navigator.serviceWorker.register('/sw.js').catch(() => { /* Browser installation remains optional. */ }); });
}
