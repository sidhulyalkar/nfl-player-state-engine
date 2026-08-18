import { useState } from 'react';
import App from './App';
import { DraftWarRoom } from './components/DraftWarRoom';

export default function OperationalApp() {
  const [surface, setSurface] = useState<'draft' | 'console'>('draft');
  if (surface === 'draft') {
    return <DraftWarRoom onOpenConsole={() => setSurface('console')} />;
  }
  return <div className="operational-console">
    <button className="back-to-draft" onClick={() => setSurface('draft')}>← Draft War Room</button>
    <App />
  </div>;
}
