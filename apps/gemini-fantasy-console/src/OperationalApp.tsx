import { useState } from 'react';
import App from './App';
import { DraftDecisionConsole } from './components/DraftDecisionConsole';

export default function OperationalApp() {
  const [surface, setSurface] = useState<'draft' | 'console'>('draft');
  if (surface === 'draft') {
    return <DraftDecisionConsole onOpenConsole={() => setSurface('console')} />;
  }
  return <div className="operational-console">
    <button className="back-to-draft" onClick={() => setSurface('draft')}>← Decision Console</button>
    <App />
  </div>;
}
