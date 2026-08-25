import { useEffect, useMemo, useState } from 'react';
import { Activity, AlertTriangle, CalendarDays, CheckCircle2, ShieldCheck } from 'lucide-react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { api } from '../lib/api';
import type { ShadowSeasonResponse } from '../lib/shadowSeasonTypes';
import { ModeBadge } from './ModeBadge';

function metric(value: number | null | undefined, digits = 2) {
  return value == null || !Number.isFinite(value) ? '—' : value.toFixed(digits);
}

function percent(value: number | null | undefined, digits = 1) {
  return value == null || !Number.isFinite(value) ? '—' : `${(value * 100).toFixed(digits)}%`;
}

function checkpointLabel(value: string) {
  return value.replaceAll('_', ' ').toLowerCase().replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function LiveShadowSeasonPanel() {
  const [payload, setPayload] = useState<ShadowSeasonResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    api.shadowSeason(2026).then((result) => {
      if (!active) return;
      setPayload(result);
      setError(null);
    }).catch((reason) => {
      if (!active) return;
      setError(reason instanceof Error ? reason.message : 'Live shadow-season evidence unavailable.');
    });
    return () => { active = false; };
  }, []);

  const checkpointChart = useMemo(() => (payload?.by_checkpoint ?? [])
    .filter((row) => row.production.n > 0)
    .map((row) => ({
      checkpoint: checkpointLabel(row.checkpoint),
      coverage: (row.production.interval_80_coverage ?? 0) * 100,
      q50Mae: row.production.q50_mae ?? 0,
      graphMae: row.challenger.n > 0 ? row.challenger.q50_mae ?? null : null,
      settled: row.settled_snapshots,
    })), [payload]);

  const overall = payload?.overall.production;
  const challenger = payload?.overall.challenger;
  const noEvidence = payload != null && payload.snapshot_count === 0;

  return <section className="wide">
    <section className="panel model-observatory-hero wide">
      <div>
        <div className="badge-line"><span className="eyebrow">2026 shadow season</span><ModeBadge mode="live"/></div>
        <h2>What did the model know before kickoff?</h2>
        <p>Immutable weekly checkpoints turn the live season into prospective evidence. Settlements score the frozen forecast later without rewriting what the system knew at the cutoff.</p>
      </div>
      <div className="authority-chip"><ShieldCheck size={18}/><div><span>Authority boundary</span><strong>Production stays direct quantile</strong><small>Player State Graph remains research-only · no automatic promotion</small></div></div>
    </section>

    {error && <section className="panel observatory-error wide"><AlertTriangle size={18}/><div><strong>Live shadow ledger unavailable.</strong><span>{error}</span></div></section>}

    {noEvidence && <section className="panel wide">
      <div className="empty-state"><CalendarDays size={20}/><div><strong>Shadow ledger armed. No 2026 checkpoints recorded yet.</strong><span>The screen will populate only after an immutable live checkpoint is written. Preseason emptiness is not replaced with synthetic metrics.</span></div></div>
    </section>}

    {payload && payload.snapshot_count > 0 && <>
      <div className="metric-grid wide observatory-metrics">
        <section className="metric-card"><div className="metric-icon"><CalendarDays size={20}/></div><span>Frozen checkpoints</span><strong>{payload.snapshot_count}</strong><small>{payload.settlement_count} settled · {payload.unsettled_snapshot_ids.length} awaiting outcomes</small></section>
        <section className="metric-card"><div className="metric-icon"><Activity size={20}/></div><span>Live q50 MAE</span><strong>{metric(overall?.q50_mae)}</strong><small>{overall?.n ?? 0} settled player-checkpoints</small></section>
        <section className="metric-card"><div className="metric-icon"><CheckCircle2 size={20}/></div><span>Live 80% coverage</span><strong>{percent(overall?.interval_80_coverage)}</strong><small>target 80% · width {metric(overall?.mean_interval_width)}</small></section>
        <section className="metric-card"><div className="metric-icon"><ShieldCheck size={20}/></div><span>Ledger integrity</span><strong>{payload.health.integrity_verified ? 'Verified' : 'Blocked'}</strong><small>{payload.health.integrity_failures.length ? `${payload.health.integrity_failures.length} integrity failures` : 'SHA-256 checkpoint + settlement linkage'}</small></section>
      </div>

      <section className="panel chart-panel wide">
        <div className="panel-heading"><div><span className="eyebrow">Prospective calibration</span><h2>Coverage by information checkpoint</h2></div><small>Only settled live evidence is plotted. Historical backtests are intentionally separate.</small></div>
        {checkpointChart.length ? <ResponsiveContainer width="100%" height={310}>
          <BarChart data={checkpointChart}>
            <CartesianGrid strokeDasharray="3 3"/>
            <XAxis dataKey="checkpoint"/>
            <YAxis domain={[0, 100]} unit="%"/>
            <Tooltip formatter={(value) => typeof value === 'number' ? `${value.toFixed(1)}%` : value}/>
            <Legend/>
            <ReferenceLine y={80} strokeDasharray="6 4" label="80% target"/>
            <Bar dataKey="coverage" name="Production 80% coverage"/>
          </BarChart>
        </ResponsiveContainer> : <div className="empty-state"><AlertTriangle size={18}/><span>Checkpoints exist, but none have settled player outcomes yet.</span></div>}
      </section>

      <div className="contract-grid wide">
        {(payload.by_checkpoint ?? []).map((row) => <article key={row.checkpoint}>
          <strong>{checkpointLabel(row.checkpoint)}</strong>
          <span>{row.snapshots} frozen · {row.settled_snapshots} settled · {row.settled_rows} player outcomes</span>
          <small>Production MAE {metric(row.production.q50_mae)} · coverage {percent(row.production.interval_80_coverage)}</small>
        </article>)}
      </div>

      <section className="panel observatory-contract wide">
        <div><ShieldCheck size={20}/><div><span className="eyebrow">Live evidence contract</span><h2>Forecast quality is not decision-value proof</h2></div></div>
        <div className="contract-grid">
          <article><strong>Production</strong><span>{payload.authority.production.replaceAll('_', ' ')} remains the live authority regardless of this panel.</span></article>
          <article><strong>Research challenger</strong><span>{challenger && challenger.n > 0 ? `Graph live q50 MAE ${metric(challenger.q50_mae)} across ${challenger.n} settled rows.` : 'No settled challenger evidence yet.'}</span></article>
          <article><strong>Settlement</strong><span>Realized outcomes are append-only companions linked to the original checkpoint digest.</span></article>
          <article><strong>Promotion</strong><span>{payload.authority.promotion_is_automatic ? 'Unexpected automatic authority is enabled.' : 'No chart or live metric can automatically promote a challenger.'}</span></article>
        </div>
      </section>
    </>}
  </section>;
}
