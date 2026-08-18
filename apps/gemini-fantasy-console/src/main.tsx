import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import OperationalApp from './OperationalApp';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <OperationalApp />
  </StrictMode>,
);
