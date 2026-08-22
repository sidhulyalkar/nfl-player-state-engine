import { FlaskConical, ShieldCheck } from 'lucide-react';
import { ModelDiagnosticsPanel } from './ModelDiagnosticsPanel';

export function ModelObservatoryPortal({ onOpenLeagueOS }: { onOpenLeagueOS: () => void }) {
  return <div className="portal-shell model-portal">
    <header className="portal-header">
      <div><span className="eyebrow">Evidence, calibration, drift and authority</span><h1>Model Observatory</h1><p>Inspect the frozen evidence behind the engine before trusting a new layer. Calibration and sharpness live beside promotion boundaries, not behind them.</p></div>
      <div className="portal-actions"><button onClick={onOpenLeagueOS}><FlaskConical size={16}/>Open full research lab</button></div>
    </header>
    <div className="observatory-principles"><div><ShieldCheck size={17}/><strong>Production stays explicit</strong><span>The direct player quantile model remains authoritative until a challenger clears frozen promotion gates.</span></div><div><FlaskConical size={17}/><strong>Research stays inspectable</strong><span>Position and season diagnostics make undercoverage, drift and weak evidence visible instead of averaging them away.</span></div></div>
    <ModelDiagnosticsPanel/>
  </div>;
}
