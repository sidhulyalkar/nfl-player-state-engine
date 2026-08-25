import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, CheckCircle2, Database, Gauge, ShieldCheck, TrendingUp } from 'lucide-react';
import {
  Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from 'recharts';
import type { ModelObservatoryResponse } from '../../shared/types';
import { api } from '../lib/api';
import { EvidenceFactoryPanel } from './EvidenceFactoryPanel';
import { LiveShadowSeasonPanel } from './LiveShadowSeasonPanel';
import { ModeBadge } from './ModeBadge';
import { ShadowEvaluationPanel } from './ShadowEvaluationPanel';

function metric(value: number | null | undefined, digits = 3) {
  return value == null || !Number.isFinite(value) ? '—' : value.toFixed(digits);
}

function percent(value: number | null | undefined, digits = 1) {
  return value == null || !Number.isFinite(value) ? '—' : `${(value * 100).toFixed(digits)}%`;
}

export function ModelDiagnosticsPanel() {
  const [payload, setPayload] = useState<ModelObservatoryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    api.modelObservatory().then((result) => {
      if (!active) return;
      setPayload(result);
      setError(null);
    }).catch((reason) => {
      if (!active) return;
      setError(reason instanceof Error ? reason.message : 'Model observatory unavailable.');
    });
    return () => { active = false; };
  }, []);

  const positions = useMemo(() => (payload?.diagnostics.by_position ?? []).map((row) => ({
    position: row.position,
    coverage: (row.empirical_80_coverage ?? 0) * 100,
    target: 80,
    mae: row.q50_mae ?? 0,
    pinball: row.mean_pinball ?? 0,
    width: row.mean_interval_width ?? 0,
    rows: row.rows,
  })), [payload]);

  const seasons = useMemo(() => (payload?.diagnostics.by_season ?? []).map((row) => ({
    season: row.season,
    coverage: (row.empirical_80_coverage ?? 0) * 100,
    mae: row.q50_mae ?? 0,
    width: row.mean_interval_width ?? 0,
    rows: row.rows,
  })), [payload]);

  const overall = payload?.diagnostics.overall;
  const health = payload?.artifact_health;
  const authority = payload?.authority;
  const graphHealth = payload?.player_state_graph?.health;

  return <div className="model-observatory-block">
    <section className="panel model-observatory-hero wide">
      <div><div className="badge-line"><span className="eyebrow">Model observatory</span><ModeBadge mode="historical"/></div><h2>Calibration before confidence</h2><p>Frozen out-of-sample diagnostics stay visually separate from live projections. The research graph can earn promotion here, but this screen cannot grant it by appearance alone.</p></div>
      <div className="authority-chip"><ShieldCheck size={18}/><div><span>Production champion</span><strong>{authority?.production_champion?.replaceAll('_', ' ') ?? 'Loading'}</strong><small>Player State Graph · {authority?.player_state_graph?.replaceAll('_', ' ') ?? 'research challenger'}</small></div></div>
    </section>

    {error && <section className="panel observatory-error wide"><AlertTriangle size={18}/><div><strong>Model observatory unavailable.</strong><span>{error}</span></div></section>}

    <div className="metric-grid wide observatory-metrics">
      <section className="metric-card"><div className="metric-icon"><Gauge size={20}/></div><span>Empirical 80% coverage</span><strong>{percent(overall?.empirical_80_coverage)}</strong><small>{overall?.calibration_status?.replaceAll('_', ' ').toLowerCase() ?? 'diagnostic loading'}</small></section>
      <section className="metric-card"><div className="metric-icon"><TrendingUp size={20}/></div><span>q50 MAE</span><strong>{metric(overall?.q50_mae, 2)}</strong><small>held-out median error</small></section>
      <section className="metric-card"><div className="metric-icon"><Database size={20}/></div><span>Mean pinball</span><strong>{metric(overall?.mean_pinball)}</strong><small>q10 / q50 / q90 average</small></section>
      <section className="metric-card"><div className="metric-icon"><CheckCircle2 size={20}/></div><span>Research artifacts</span><strong>{health ? `${health.available}/${health.total}` : '—'}</strong><small>{graphHealth?.available ? 'state graph mounted' : health?.missing?.length ? `${health.missing.length} missing` : 'core research mounted'}</small></section>
    </div>

    <EvidenceFactoryPanel/>
    <LiveShadowSeasonPanel/>
    <ShadowEvaluationPanel evaluation={payload?.player_state_graph?.shadow_evaluation}/>

    <div className="observatory-chart-grid wide">
      <section className="panel chart-panel">
        <div className="panel-heading"><div><span className="eyebrow">Position calibration</span><h2>Does the 80% interval actually cover 80%?</h2></div></div>
        {positions.length ? <ResponsiveContainer width="100%" height={300}><BarChart data={positions}><CartesianGrid strokeDasharray="3 3"/><XAxis dataKey="position"/><YAxis domain={[0, 100]} unit="%"/><Tooltip formatter={(value) => typeof value === 'number' ? `${value.toFixed(1)}%` : value}/><ReferenceLine y={80} strokeDasharray="6 4" label="80% target"/><Bar dataKey="coverage" name="Empirical coverage"/></BarChart></ResponsiveContainer> : <div className="empty-state"><AlertTriangle size={18}/><span>Position diagnostics need enough frozen rows to clear the minimum sample gate.</span></div>}
      </section>
      <section className="panel chart-panel">
        <div className="panel-heading"><div><span className="eyebrow">Error and sharpness</span><h2>Accuracy by position</h2></div></div>
        {positions.length ? <ResponsiveContainer width="100%" height={300}><BarChart data={positions}><CartesianGrid strokeDasharray="3 3"/><XAxis dataKey="position"/><YAxis/><Tooltip/><Legend/><Bar dataKey="mae" name="q50 MAE"/><Bar dataKey="pinball" name="Mean pinball"/><Bar dataKey="width" name="80% interval width"/></BarChart></ResponsiveContainer> : <div className="empty-state"><AlertTriangle size={18}/><span>No position-level diagnostic rows were returned.</span></div>}
      </section>
    </div>

    <section className="panel chart-panel wide">
      <div className="panel-heading"><div><span className="eyebrow">Season drift</span><h2>Calibration and median error over time</h2></div><small>Coverage target remains 80% across seasons.</small></div>
      {seasons.length ? <ResponsiveContainer width="100%" height={320}><LineChart data={seasons}><CartesianGrid strokeDasharray="3 3"/><XAxis dataKey="season"/><YAxis yAxisId="coverage" domain={[0, 100]} unit="%"/><YAxis yAxisId="error" orientation="right"/><Tooltip/><Legend/><ReferenceLine yAxisId="coverage" y={80} strokeDasharray="6 4"/><Line yAxisId="coverage" type="monotone" dataKey="coverage" name="80% coverage" strokeWidth={2}/><Line yAxisId="error" type="monotone" dataKey="mae" name="q50 MAE" strokeWidth={2}/></LineChart></ResponsiveContainer> : <div className="empty-state"><AlertTriangle size={18}/><span>Season-level drift diagnostics are unavailable for the mounted artifact.</span></div>}
    </section>

    <section className="panel observatory-contract wide">
      <div><ShieldCheck size={20}/><div><span className="eyebrow">Interpretation contract</span><h2>What these charts mean</h2></div></div>
      <div className="contract-grid"><article><strong>Coverage</strong><span>Observed share of outcomes between q10 and q90. The nominal target is 80%.</span></article><article><strong>Sharpness</strong><span>Narrower intervals are useful only when coverage remains calibrated. Width alone is not a win.</span></article><article><strong>Pinball</strong><span>Quantile loss rewards accurate distributional forecasts and penalizes misses asymmetrically.</span></article><article><strong>Authority</strong><span>Historical diagnostics inform promotion gates. They do not silently replace the live production champion.</span></article></div>
    </section>
  </div>;
}
