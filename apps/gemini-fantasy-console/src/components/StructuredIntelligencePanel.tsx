import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, CheckCircle2, FileSearch, LockKeyhole, ShieldCheck } from 'lucide-react';
import type { StructuredIntelligenceResponse } from '../lib/structuredIntelligenceTypes';
import { api } from '../lib/api';

function metric(value: number | null | undefined, digits = 2) {
  return value == null || !Number.isFinite(value) ? '—' : value.toFixed(digits);
}

function familyLabel(value: string) {
  return value.replaceAll('_', ' ');
}

export function StructuredIntelligencePanel() {
  const [payload, setPayload] = useState<StructuredIntelligenceResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    api.structuredIntelligence().then((result) => {
      if (!active) return;
      setPayload(result);
      setError(null);
    }).catch((reason) => {
      if (!active) return;
      setError(reason instanceof Error ? reason.message : 'Structured intelligence unavailable.');
    });
    return () => { active = false; };
  }, []);

  const activation = payload?.activation ?? payload?.health.activation;
  const conflicts = useMemo(() => [...(payload?.states ?? [])]
    .filter((row) => row.conflict_score > 0)
    .sort((a, b) => b.conflict_score - a.conflict_score)
    .slice(0, 4), [payload]);

  if (error) {
    return <section className="panel wide observatory-error">
      <AlertTriangle size={18}/><div><strong>Structured intelligence unavailable.</strong><span>{error}</span></div>
    </section>;
  }

  const available = payload?.data_mode === 'STRUCTURED_EVIDENCE';
  const healthy = payload?.health.integrity_verified;
  const enabled = activation?.enabled ?? [];
  const shadow = activation?.shadow ?? [];
  const disabled = activation?.disabled ?? [];

  return <section className="panel wide">
    <div className="panel-heading">
      <div>
        <div className="badge-line"><span className="eyebrow">Structured intelligence</span><span className="mode-badge historical">RESEARCH EVIDENCE</span></div>
        <h2>Football information stays evidence until it earns authority</h2>
        <p>Official availability and structured reporting share one timestamped, contradiction-aware ledger. This surface can inspect evidence and activation state, but it cannot promote or rewrite either.</p>
      </div>
      <div className="authority-chip">
        {healthy ? <ShieldCheck size={18}/> : <AlertTriangle size={18}/>}<div><span>Ledger integrity</span><strong>{payload ? healthy ? 'Verified' : 'Failed' : 'Loading'}</strong><small>{payload?.automatic_promotion === false ? 'automatic promotion disabled' : 'authority loading'}</small></div>
      </div>
    </div>

    <div className="metric-grid observatory-metrics">
      <section className="metric-card"><div className="metric-icon"><FileSearch size={20}/></div><span>Eligible claims</span><strong>{payload?.claim_count ?? '—'}</strong><small>{payload?.effective_claim_count ?? '—'} effective at cutoff</small></section>
      <section className="metric-card"><div className="metric-icon"><CheckCircle2 size={20}/></div><span>Resolved states</span><strong>{payload?.state_count ?? '—'}</strong><small>{payload?.states?.length ? 'point-in-time evidence states' : 'no mounted state evidence'}</small></section>
      <section className="metric-card"><div className="metric-icon"><AlertTriangle size={20}/></div><span>Conflict</span><strong>{metric(payload?.summary?.max_conflict_score)}</strong><small>{payload?.summary?.states_with_conflict ?? 0} states with opposing evidence</small></section>
      <section className="metric-card"><div className="metric-icon"><LockKeyhole size={20}/></div><span>Production-enabled families</span><strong>{enabled.length}</strong><small>{shadow.length} shadow · {disabled.length} disabled</small></section>
    </div>

    {!payload && <div className="empty-state"><span>Loading timestamped evidence ledger…</span></div>}
    {payload && !available && <div className="empty-state"><AlertTriangle size={18}/><span>No structured evidence is mounted for the current cutoff. The Observatory does not synthesize substitute claims.</span></div>}

    {activation && <div className="contract-grid">
      {Object.entries(activation.families).map(([family, entry]) => <article key={family}>
        <strong>{familyLabel(family)}</strong>
        <span>{entry.status.toUpperCase()} · {entry.experiment_id ? `experiment ${entry.experiment_id}` : 'no promotion experiment attached'}</span>
      </article>)}
    </div>}

    {conflicts.length > 0 && <div className="contract-grid">
      {conflicts.map((row) => <article key={`${row.player_id}:${row.latent_state}`}>
        <strong>{row.player_id} · {familyLabel(row.latent_state)}</strong>
        <span>Conflict {row.conflict_score.toFixed(2)} · consensus {row.consensus_signal.toFixed(2)} · {row.source_count} sources</span>
      </article>)}
    </div>}

    <div className="observatory-contract">
      <div><LockKeyhole size={20}/><div><span className="eyebrow">Authority contract</span><h2>Collection is not activation</h2></div></div>
      <div className="contract-grid"><article><strong>Official ≠ certain</strong><span>First-party designations carry stronger evidence class, but still do not guarantee participation or workload.</span></article><article><strong>Conflict stays visible</strong><span>Opposing reports increase disagreement instead of being collapsed by last-write-wins logic.</span></article><article><strong>Corrections are temporal</strong><span>Later corrections suppress earlier claims only after the correction itself became available.</span></article><article><strong>Promotion is manual</strong><span>Every feature family remains disabled or shadow-only until frozen evidence and explicit approval exist.</span></article></div>
    </div>
  </section>;
}
