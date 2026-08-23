import { AlertTriangle, CheckCircle2, FlaskConical, ShieldCheck } from 'lucide-react';
import type { ShadowEvaluationResponse } from '../../shared/types';

function metric(value: number | null | undefined, digits = 3) {
  return value == null || !Number.isFinite(value) ? '—' : value.toFixed(digits);
}

function pct(value: number | null | undefined, digits = 1) {
  return value == null || !Number.isFinite(value) ? '—' : `${(value * 100).toFixed(digits)}%`;
}

export function ShadowEvaluationPanel({ evaluation }: { evaluation?: ShadowEvaluationResponse }) {
  if (!evaluation || evaluation.data_mode === 'UNAVAILABLE') {
    return <section className="panel shadow-evaluation-panel wide unavailable">
      <AlertTriangle size={19}/><div><span className="eyebrow">Player State Graph shadow replay</span><h2>Paired evaluation unavailable</h2><p>{evaluation?.reason?.replaceAll('_', ' ') ?? 'Mount a contract-tagged Player State Graph run with overlapping frozen champion predictions.'}</p></div>
    </section>;
  }

  const metrics = evaluation.metrics;
  const blocked = evaluation.promotion_status !== 'eligible';
  const effect = metrics?.pinball_effect_champion_minus_challenger;

  return <section className="panel shadow-evaluation-panel wide">
    <div className="panel-heading"><div><span className="eyebrow">Player State Graph shadow replay</span><h2>Champion vs. challenger, paired on the same frozen games</h2><p>A positive pinball effect means the graph challenger had lower quantile loss. Promotion remains a separate evidence decision.</p></div><span className={`promotion-state ${blocked ? 'blocked' : 'eligible'}`}>{blocked ? <ShieldCheck size={16}/> : <CheckCircle2 size={16}/>} {blocked ? 'PROMOTION BLOCKED' : 'EVIDENCE ELIGIBLE'}</span></div>

    <div className="shadow-eval-metrics">
      <article><span>Paired games</span><strong>{evaluation.paired_rows ?? '—'}</strong><small>{evaluation.seasons ?? '—'} seasons</small></article>
      <article><span>Champion pinball</span><strong>{metric(metrics?.champion_mean_pinball)}</strong><small>direct quantile model</small></article>
      <article><span>Graph pinball</span><strong>{metric(metrics?.challenger_mean_pinball)}</strong><small>research challenger</small></article>
      <article className={effect != null && effect > 0 ? 'positive' : ''}><span>Paired effect</span><strong>{metric(effect)}</strong><small>champion minus challenger</small></article>
      <article><span>Champion coverage</span><strong>{pct(metrics?.champion_80_coverage)}</strong><small>nominal target 80%</small></article>
      <article><span>Graph coverage</span><strong>{pct(metrics?.challenger_80_coverage)}</strong><small>must retain calibration</small></article>
    </div>

    <div className="shadow-eval-bottom">
      <div className="shadow-eval-compare"><FlaskConical size={18}/><div><strong>Median accuracy</strong><span>Champion MAE {metric(metrics?.champion_q50_mae, 2)} · Graph MAE {metric(metrics?.challenger_q50_mae, 2)}</span></div><div><strong>Sharpness</strong><span>Champion width {metric(metrics?.champion_mean_width, 2)} · Graph width {metric(metrics?.challenger_mean_width, 2)}</span></div></div>
      <div className="blocker-panel"><strong>Promotion blockers</strong>{evaluation.blockers?.length ? <div>{evaluation.blockers.map((blocker) => <span key={blocker}>{blocker.replaceAll('_', ' ')}</span>)}</div> : <p>No blockers reported by the current policy.</p>}</div>
    </div>
    <p className="shadow-eval-note">{evaluation.note}</p>
  </section>;
}
