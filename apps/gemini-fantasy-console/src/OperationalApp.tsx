import { useState } from 'react';
import App from './App';
import { DraftDecisionConsole } from './components/DraftDecisionConsole';
import { IntelligencePortal } from './components/IntelligencePortal';
import { ModelObservatoryPortal } from './components/ModelObservatoryPortal';
import './workspace.css';

type Surface = 'draft' | 'intelligence' | 'league' | 'model';

const surfaces: Array<{ key: Surface; label: string; description: string }> = [
  { key: 'draft', label: 'Draft Room', description: 'Live pick decisions' },
  { key: 'intelligence', label: 'Player Intelligence', description: 'Full player dossiers' },
  { key: 'league', label: 'League OS', description: 'Trades, waivers, lineup, NFL' },
  { key: 'model', label: 'Model Observatory', description: 'Calibration and evidence' },
];

export default function OperationalApp() {
  const [surface, setSurface] = useState<Surface>('draft');

  return <div className="workspace-root">
    <nav className="workspace-switcher" aria-label="Modelling workspace">
      <div className="workspace-identity"><div>4D</div><span><strong>Fourth Down Lab</strong><small>modelling workspace</small></span></div>
      <div className="workspace-tabs">{surfaces.map((item) => <button key={item.key} className={surface === item.key ? 'active' : ''} onClick={() => setSurface(item.key)}><strong>{item.label}</strong><small>{item.description}</small></button>)}</div>
      <div className="workspace-status"><i/><span>Server-side model truth</span></div>
    </nav>
    <div className="workspace-surface">
      {surface === 'draft' && <DraftDecisionConsole onOpenConsole={() => setSurface('league')} />}
      {surface === 'intelligence' && <IntelligencePortal/>}
      {surface === 'league' && <div className="operational-console"><App/></div>}
      {surface === 'model' && <ModelObservatoryPortal onOpenLeagueOS={() => setSurface('league')}/>} 
    </div>
  </div>;
}
