import { useEffect, useState } from 'react';
import App from './App';
import { DraftDayDoctorBanner } from './components/DraftDayDoctorBanner';
import { DraftDecisionConsole } from './components/DraftDecisionConsole';
import { IntelligencePortal } from './components/IntelligencePortal';
import { ModelObservatoryPortal } from './components/ModelObservatoryPortal';
import { NflHubPortal } from './components/NflHubPortal';
import { PortfolioPortal } from './components/PortfolioPortal';
import './workspace.css';
import './shadow-workspace.css';

type Surface = 'draft' | 'nfl' | 'intelligence' | 'portfolio' | 'league' | 'model';

type WorkspaceRoute = {
  surface: Surface;
  leagueId?: string;
  playerId?: string;
};

const surfaces: Array<{ key: Surface; label: string; description: string }> = [
  { key: 'draft', label: 'Draft Room', description: 'Live pick decisions' },
  { key: 'nfl', label: 'NFL Hub', description: 'What changed + impact' },
  { key: 'intelligence', label: 'Player Intelligence', description: 'Full player dossiers' },
  { key: 'portfolio', label: 'Portfolio', description: 'Cross-league exposure' },
  { key: 'league', label: 'League OS', description: 'Trades, waivers, lineup' },
  { key: 'model', label: 'Model Observatory', description: 'Calibration and evidence' },
];

const surfaceKeys = new Set<Surface>(surfaces.map((item) => item.key));

function readWorkspaceRoute(): WorkspaceRoute {
  if (typeof window === 'undefined') return { surface: 'draft' };
  const params = new URLSearchParams(window.location.search);
  const requested = params.get('workspace') as Surface | null;
  return {
    surface: requested && surfaceKeys.has(requested) ? requested : 'draft',
    leagueId: params.get('league') || undefined,
    playerId: params.get('player') || undefined,
  };
}

function writeWorkspaceSurface(surface: Surface, mode: 'push' | 'replace' = 'push') {
  if (typeof window === 'undefined') return;
  const url = new URL(window.location.href);
  url.searchParams.set('workspace', surface);
  const method = mode === 'replace' ? 'replaceState' : 'pushState';
  window.history[method](null, '', url);
}

export default function OperationalApp() {
  const [route, setRoute] = useState<WorkspaceRoute>(readWorkspaceRoute);

  useEffect(() => {
    const handlePopState = () => setRoute(readWorkspaceRoute());
    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, []);

  function navigate(surface: Surface, mode: 'push' | 'replace' = 'push') {
    writeWorkspaceSurface(surface, mode);
    setRoute({ ...readWorkspaceRoute(), surface });
  }

  return <div className="workspace-root">
    <nav className="workspace-switcher" aria-label="Modelling workspace">
      <div className="workspace-identity"><div>4D</div><span><strong>Fourth Down Lab</strong><small>modelling workspace</small></span></div>
      <div className="workspace-tabs">{surfaces.map((item) => <button key={item.key} className={route.surface === item.key ? 'active' : ''} onClick={() => navigate(item.key)}><strong>{item.label}</strong><small>{item.description}</small></button>)}</div>
      <div className="workspace-status"><i/><span>Server-side model truth</span></div>
    </nav>
    <div className="workspace-surface">
      {route.surface === 'draft' && <><DraftDayDoctorBanner/><DraftDecisionConsole onOpenConsole={() => navigate('league')} /></>}
      {route.surface === 'nfl' && <NflHubPortal/>}
      {route.surface === 'intelligence' && <IntelligencePortal initialLeagueId={route.leagueId} initialPlayerId={route.playerId}/>} 
      {route.surface === 'portfolio' && <PortfolioPortal/>}
      {route.surface === 'league' && <div className="operational-console"><App/></div>}
      {route.surface === 'model' && <ModelObservatoryPortal onOpenLeagueOS={() => navigate('league')}/>} 
    </div>
  </div>;
}
