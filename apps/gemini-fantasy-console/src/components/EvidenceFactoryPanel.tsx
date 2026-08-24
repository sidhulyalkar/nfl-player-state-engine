import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, CheckCircle2, Database, FlaskConical, ShieldCheck } from 'lucide-react';
import type { EvidenceFactoryResponse, EvidencePairComparisonRow } from '../lib/evidenceTypes';
import { api } from '../lib/api';
import './evidence-factory.css';

function metric(value: number | null | undefined, digits = 3) {
  return value == null || !Number.isFinite(value) ? '—' : value.toFixed(digits);
}

function pct(value: number | null | undefined, digits = 1) {
  return value == null || !Number.isFinite(value) ? '—' : `${(value * 100).toFixed(digits)}%`;
}

function blockers(row: EvidencePairComparisonRow) {
  if (!row.blockers) return [];
  return row.blockers.split('|').filter(Boolean);
}

function label(value: string) {
  return value.replaceAll('_', ' ');
}

export function EvidenceFactoryPanel() {
  const [payload, setPayload] = useState<EvidenceFactoryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    api.evidenceFactory().then((result) => {
      if (!active) return;
      setPayload(result);
      setError(null);
    }).catch((reason) => {
      if (!active) return;
      setError(reason instanceof Error ? reason.message : 'Evidence Factory unavailable.');
    });
    return () => { active = false; };
  }, []);

  const comparisons = payload?.paired_comparisons ?? [];
  const controls = payload?.negative_controls ?? [];
  const sorted = useMemo(
    () => [...comparisons].sort(
      (a, b) => b.pinball_effect_champion_minus_challenger - a.pinball_effect_champion_minus_challenger,
    ),
    [comparisons],
  );
  const controlsByComparison = useMemo(
    () => new Map(controls.map((row) => [`${row.target}|${row.method}`, row])),
    [controls],
  );
  const best = sorted[0];
  const eligible = comparisons.filter((row) => row.promotion_status === 'eligible').length;
  const controlsPassed = controls.filter((row) => row.passed).length;
  const graphStatus = payload?.manifest?.graph;
  const graphIncluded = Boolean(graphStatus && graphStatus['included'] === true);
  const graphReason = typeof graphStatus?.['reason'] === 'string'
    ? String(graphStatus['reason']).replaceAll('_', ' ')
    : 'graph status unavailable';
  const championCount = Object.keys(payload?.manifest?.champion_methods ?? {}).length;

  if (error) {
    return <section className="panel observatory-error wide"><AlertTriangle size={18}/><div><strong>Evidence Factory unavailable.</strong><span>{error}</span></div></section>;
  }

  if (!payload) {
    return <section className="panel shadow-evaluation-panel wide"><Database size={18}/><div><span className="eyebrow">Evidence Factory</span><h2>Loading frozen model ledger</h2><p>Reading canonical player-week comparisons and promotion blockers.</p></div></section>;
  }

  if (payload.data_mode === 'UNAVAILABLE') {
    return <section className="panel shadow-evaluation-panel wide unavailable"><AlertTriangle size={19}/><div><span className="eyebrow">Evidence Factory</span><h2>No frozen evidence bundle mounted</h2><p>Run <code>scripts/run_evidence_factory.py</code> and mount its artifact directory. The product will not invent comparison results.</p></div></section>;
  }

  return <section className="panel shadow-evaluation-panel wide evidence-factory-panel">
    <div className="panel-heading">
      <div><span className="eyebrow">Evidence Factory · frozen player-week benchmark</span><h2>One scoreboard, target-aware champions</h2><p>All effects are paired on identical evaluable player-weeks. Positive pinball effect favors the challenger, but every target is compared with its configured production champion and promotion remains fail closed.</p></div>
      <span className="promotion-state blocked"><ShieldCheck size={16}/> RESEARCH EVIDENCE ONLY</span>
    </div>

    <div className="shadow-eval-metrics">
      <article><span>Methods</span><strong>{payload.method_summary?.length ?? 0}</strong><small>same metric contract</small></article>
      <article><span>Paired challengers</span><strong>{comparisons.length}</strong><small>vs each target champion</small></article>
      <article className={best && best.pinball_effect_champion_minus_challenger > 0 ? 'positive' : ''}><span>Best paired effect</span><strong>{metric(best?.pinball_effect_champion_minus_challenger)}</strong><small>{best ? `${label(best.challenger)} · ${label(best.target)}` : 'no challenger mounted'}</small></article>
      <article className={controls.length > 0 && controlsPassed === controls.length ? 'positive' : ''}><span>Identity controls</span><strong>{controlsPassed}/{controls.length}</strong><small>real mapping beats permutation</small></article>
      <article><span>Target champions</span><strong>{championCount || '—'}</strong><small>production authority is target-specific</small></article>
      <article><span>Artifact health</span><strong>{payload.health.available_count}/{payload.health.expected_count}</strong><small>{payload.health.available ? 'complete bundle' : `${payload.health.missing.length} missing`}</small></article>
    </div>

    <div className="shadow-eval-bottom">
      <div className="shadow-eval-compare"><FlaskConical size={18}/><div><strong>Frozen identity contract</strong><span>Target + method + player + season + week must be unique. Realized outcomes must agree before pairing.</span></div><div><strong>Identity negative control</strong><span>Forecast triplets are reassigned within season and position. The real player mapping must beat that control with its paired 95% interval above zero.</span></div></div>
      <div className="blocker-panel"><strong>Run provenance</strong><p>{payload.manifest?.git_sha ? `Git ${payload.manifest.git_sha.slice(0, 12)}` : 'Git SHA unavailable'} · SHA-256 inputs and outputs recorded · Benjamini-Hochberg FDR applied. Graph: {graphIncluded ? 'included under exact PPR scoring' : graphReason}.</p></div>
    </div>

    {sorted.length > 0 && <div className="evidence-comparison-list">
      {sorted.map((row) => {
        const control = controlsByComparison.get(`${row.target}|${row.challenger}`);
        return <article className="shadow-eval-compare" key={row.experiment_id}>
          <div><strong>{label(row.challenger)}</strong><span>{label(row.target)} · champion {label(row.champion)} · {row.paired_rows} paired rows across {row.paired_seasons} seasons</span></div>
          <div><strong>Effect {metric(row.pinball_effect_champion_minus_challenger)}</strong><span>CI {metric(row.ci_low)} to {metric(row.ci_high)} · FDR q {metric(row.fdr_q_value)} · improve {pct(row.probability_improves)}</span></div>
          <div><strong>Coverage {pct(row.challenger_80_coverage)}</strong><span>MAE {metric(row.challenger_q50_mae, 2)} · width {metric(row.challenger_mean_width_80, 2)} · data {pct(row.data_availability)} · identity control {control ? (control.passed ? 'PASS' : 'FAIL') : '—'}</span></div>
          <div className="blocker-panel"><strong>{row.promotion_status === 'eligible' ? <><CheckCircle2 size={14}/> Eligible</> : 'Blocked'}</strong><div>{blockers(row).slice(0, 4).map((blocker) => <span key={blocker}>{label(blocker)}</span>)}</div></div>
        </article>;
      })}
    </div>}
    <p className="shadow-eval-note">{payload.promotion?.note ?? 'Historical comparison is evidence, not production authority.'}</p>
  </section>;
}
