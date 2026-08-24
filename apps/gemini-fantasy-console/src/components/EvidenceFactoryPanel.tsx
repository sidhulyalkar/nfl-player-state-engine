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

function unavailableCopy(payload: EvidenceFactoryResponse) {
  if (payload.reason === 'evidence_factory_artifact_integrity_failed') {
    const failures = payload.health.integrity_failures ?? [];
    return {
      title: 'Evidence bundle failed integrity verification',
      body: failures.length > 0
        ? `Refusing unverified research evidence: ${failures.map(label).join(', ')}.`
        : 'One or more Evidence Factory artifacts do not match the SHA-256 hashes recorded by the run manifest.',
    };
  }
  if (payload.reason === 'evidence_factory_manifest_invalid') {
    return {
      title: 'Evidence manifest is invalid',
      body: 'The frozen evidence files are not trusted without a valid run_manifest.json provenance contract.',
    };
  }
  return {
    title: 'No frozen evidence bundle mounted',
    body: 'Run scripts/run_evidence_factory.py and mount its artifact directory. The product will not invent comparison results.',
  };
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
  const ordered = useMemo(
    () => [...comparisons].sort((a, b) => {
      const targetOrder = a.target.localeCompare(b.target);
      if (targetOrder !== 0) return targetOrder;
      const challengerOrder = a.challenger.localeCompare(b.challenger);
      return challengerOrder !== 0 ? challengerOrder : a.champion.localeCompare(b.champion);
    }),
    [comparisons],
  );
  const controlsByComparison = useMemo(
    () => new Map(controls.map((row) => [`${row.target}|${row.method}`, row])),
    [controls],
  );
  const methodCount = new Set((payload?.method_summary ?? []).map((row) => row.method)).size;
  const positivePairs = comparisons.filter(
    (row) => row.pinball_effect_champion_minus_challenger > 0,
  ).length;
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
    const copy = unavailableCopy(payload);
    return <section className="panel shadow-evaluation-panel wide unavailable"><AlertTriangle size={19}/><div><span className="eyebrow">Evidence Factory</span><h2>{copy.title}</h2><p>{copy.body}</p></div></section>;
  }

  return <section className="panel shadow-evaluation-panel wide evidence-factory-panel">
    <div className="panel-heading">
      <div><span className="eyebrow">Evidence Factory · frozen player-week benchmark</span><h2>Comparable evidence, target-aware champions</h2><p>Each effect is meaningful only within its own target and paired champion. Different target units are never ranked against one another, and promotion remains fail closed.</p></div>
      <span className="promotion-state blocked"><ShieldCheck size={16}/> RESEARCH EVIDENCE ONLY</span>
    </div>

    <div className="shadow-eval-metrics">
      <article><span>Distinct methods</span><strong>{methodCount}</strong><small>across mounted targets</small></article>
      <article><span>Paired challengers</span><strong>{comparisons.length}</strong><small>vs each target champion</small></article>
      <article className={positivePairs > 0 ? 'positive' : ''}><span>Positive pairs</span><strong>{positivePairs}/{comparisons.length}</strong><small>direction only, not cross-target rank</small></article>
      <article className={controls.length > 0 && controlsPassed === controls.length ? 'positive' : ''}><span>Identity controls</span><strong>{controlsPassed}/{controls.length}</strong><small>real mapping beats permutation</small></article>
      <article><span>Target champions</span><strong>{championCount || '—'}</strong><small>production authority is target-specific</small></article>
      <article><span>Promotion eligible</span><strong>{eligible}</strong><small>normally zero at isolated tier</small></article>
    </div>

    <div className="shadow-eval-bottom">
      <div className="shadow-eval-compare"><FlaskConical size={18}/><div><strong>Frozen identity contract</strong><span>Target + method + player + season + week must be unique. Realized outcomes must agree before pairing.</span></div><div><strong>Identity negative control</strong><span>Forecast triplets are reassigned within season and position. The real player mapping must beat that control with its paired 95% interval above zero.</span></div></div>
      <div className="blocker-panel"><strong>Run provenance</strong><p>{payload.manifest?.git_sha ? `Git ${payload.manifest.git_sha.slice(0, 12)}` : 'Git SHA unavailable'} · artifacts {payload.health.available_count}/{payload.health.expected_count} · SHA-256 integrity verified · run-wide Benjamini-Hochberg FDR applied. Graph: {graphIncluded ? 'included under exact PPR scoring' : graphReason}.</p></div>
    </div>

    {ordered.length > 0 && <div className="evidence-comparison-list">
      {ordered.map((row) => {
        const control = controlsByComparison.get(`${row.target}|${row.challenger}`);
        return <article className="shadow-eval-compare" key={row.experiment_id}>
          <div><strong>{label(row.challenger)}</strong><span>{label(row.target)} · champion {label(row.champion)} · {row.paired_rows} paired rows across {row.paired_seasons} seasons</span></div>
          <div><strong>Effect {metric(row.pinball_effect_champion_minus_challenger)}</strong><span>CI {metric(row.ci_low)} to {metric(row.ci_high)} · p {metric(row.p_value)} · FDR q {metric(row.fdr_q_value)}</span></div>
          <div><strong>Coverage {pct(row.challenger_80_coverage)}</strong><span>MAE {metric(row.challenger_q50_mae, 2)} · width {metric(row.challenger_mean_width_80, 2)} · data {pct(row.data_availability)} · identity control {control ? (control.passed ? 'PASS' : 'FAIL') : '—'}</span></div>
          <div className="blocker-panel"><strong>{row.promotion_status === 'eligible' ? <><CheckCircle2 size={14}/> Eligible</> : 'Blocked'}</strong><div>{blockers(row).slice(0, 4).map((blocker) => <span key={blocker}>{label(blocker)}</span>)}</div></div>
        </article>;
      })}
    </div>}
    <p className="shadow-eval-note">{payload.promotion?.note ?? 'Historical comparison is evidence, not production authority.'}</p>
  </section>;
}
