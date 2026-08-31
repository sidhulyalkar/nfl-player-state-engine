import { useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle2, Play, RefreshCw, ShieldCheck } from 'lucide-react';
import '../draft-launch.css';

type DoctorStatus = 'READY' | 'PROVISIONAL' | 'BLOCKED';
type StageStatus = 'REFRESHED' | 'PRESERVED' | 'SKIPPED' | 'FAILED';

type LaunchStage = {
  name: string;
  status: StageStatus;
  detail: string;
  data?: Record<string, unknown> | null;
};

type LaunchStatus = {
  status: DoctorStatus;
  can_open_war_room: boolean;
  authority: string;
  champion_mutated: boolean;
  model_promotion_performed: boolean;
  stages?: LaunchStage[];
  doctor: {
    status: DoctorStatus;
    blocking_reasons?: string[];
    provisional_reasons?: string[];
    checked_at_utc?: string;
  };
};

async function responseDetail(response: Response) {
  const text = await response.text();
  try {
    const payload = JSON.parse(text) as { detail?: string };
    return payload.detail ?? text;
  } catch {
    return text || response.statusText;
  }
}

function stageIcon(status: StageStatus) {
  if (status === 'REFRESHED') return <CheckCircle2 size={13}/>;
  if (status === 'FAILED') return <AlertTriangle size={13}/>;
  return <RefreshCw size={13}/>;
}

export function DraftLaunchPanel() {
  const [report, setReport] = useState<LaunchStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void fetch('/api/pse/v1/draft/launch/status')
      .then(async (response) => {
        if (!response.ok) throw new Error(await responseDetail(response));
        return response.json() as Promise<LaunchStatus>;
      })
      .then((payload) => {
        if (active) setReport(payload);
      })
      .catch((reason) => {
        if (active) setError(reason instanceof Error ? reason.message : 'Draft launch status unavailable');
      });
    return () => { active = false; };
  }, []);

  async function prepare() {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch('/api/pse/v1/draft/launch/prepare?season=2026', { method: 'POST' });
      if (!response.ok) throw new Error(await responseDetail(response));
      const payload = await response.json() as LaunchStatus;
      setReport(payload);
      window.dispatchEvent(new Event('pse:draft-state-refreshed'));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Draft preparation failed');
    } finally {
      setBusy(false);
    }
  }

  const status = report?.status ?? 'PROVISIONAL';
  const authoritySafe = report ? !report.champion_mutated && !report.model_promotion_performed : true;
  return <section className={`draft-launch-panel ${status.toLowerCase()}`}>
    <div className="draft-launch-head">
      <div className="draft-launch-title"><ShieldCheck size={18}/><div><span>DRAFT LAUNCH</span><strong>{report ? status : 'CHECKING'}</strong></div></div>
      <div className="draft-launch-copy">
        <strong>Refresh the room, not the model.</strong>
        <span>NFL state, connected league snapshots, K/DST market guidance and ADP refresh here. The approved projection champion cannot be promoted or rewritten by this control.</span>
      </div>
      <button className="draft-launch-button" onClick={() => void prepare()} disabled={busy}>
        {busy ? <RefreshCw size={15} className="spin"/> : <Play size={15}/>} {busy ? 'Preparing…' : 'Prepare Draft Room'}
      </button>
    </div>

    {report && <div className="draft-launch-meta">
      <span className={authoritySafe ? 'safe' : 'unsafe'}>{authoritySafe ? 'Champion immutable' : 'Authority violation'}</span>
      <span>{report.can_open_war_room ? 'Core War Room usable' : 'War Room still blocked'}</span>
      <span>{report.authority.replaceAll('_', ' ')}</span>
    </div>}

    {(report?.stages?.length ?? 0) > 0 && <div className="draft-launch-stages">
      {report?.stages?.map((stage) => <div className={`draft-launch-stage ${stage.status.toLowerCase()}`} key={stage.name}>
        {stageIcon(stage.status)}<strong>{stage.name.replaceAll('_', ' ').replace('league:', 'league ')}</strong><span>{stage.status}</span><small>{stage.detail}</small>
      </div>)}
    </div>}

    {error && <div className="draft-launch-error"><AlertTriangle size={14}/><span>{error}</span></div>}
  </section>;
}
