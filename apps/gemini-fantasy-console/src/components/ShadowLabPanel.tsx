import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, FlaskConical, GitCompareArrows, RefreshCw, SlidersHorizontal } from 'lucide-react';
import type { PlayerScenarioResponse, PlayerShadowResponse } from '../../shared/types';
import { api } from '../lib/api';

function metric(value: number | null | undefined, digits = 1) {
  return value == null || !Number.isFinite(value) ? '—' : value.toFixed(digits);
}

function pct(value: number | null | undefined, digits = 0) {
  return value == null || !Number.isFinite(value) ? '—' : `${(value * 100).toFixed(digits)}%`;
}

function signed(value: number | null | undefined, digits = 1) {
  return value == null || !Number.isFinite(value) ? '—' : `${value > 0 ? '+' : ''}${value.toFixed(digits)}`;
}

function OpportunityBar({
  label,
  family,
  playerId,
}: {
  label: string;
  family: PlayerShadowResponse['opportunity']['target_share'];
  playerId: string;
}) {
  if (!family) return <div className="shadow-empty">{label} unavailable.</div>;
  return <div className="opportunity-family">
    <div className="opportunity-family-head"><div><strong>{label}</strong><span>{family.normalization_applied ? 'coherent normalization applied' : 'natural support retained'}</span></div><div><b>{pct(family.coherent_modeled_total)}</b><small>modeled · {pct(family.residual_unmodeled_share)} residual</small></div></div>
    <div className="opportunity-stack">
      {family.players.map((row) => <i
        key={row.player_id}
        className={row.player_id === playerId ? 'selected' : ''}
        style={{ width: `${Math.max(0, row.coherent_share * 100)}%` }}
        title={`${row.player_id} ${pct(row.coherent_share)}`}
      />)}
      {family.residual_unmodeled_share > 0 && <i className="residual" style={{ width: `${family.residual_unmodeled_share * 100}%` }} title={`Unmodeled teammates ${pct(family.residual_unmodeled_share)}`}/>} 
    </div>
    <div className="opportunity-legend"><span>Raw modeled {pct(family.raw_modeled_total)}</span><span>Scale {metric(family.normalization_scale, 3)}</span><span>Selected player highlighted</span></div>
  </div>;
}

export function ShadowLabPanel({
  leagueId,
  playerId,
  baselineAvailability,
}: {
  leagueId: string;
  playerId: string;
  baselineAvailability?: number;
}) {
  const [shadow, setShadow] = useState<PlayerShadowResponse | null>(null);
  const [scenario, setScenario] = useState<PlayerScenarioResponse | null>(null);
  const [role, setRole] = useState(1);
  const [volume, setVolume] = useState(1);
  const [availability, setAvailability] = useState<number | undefined>(baselineAvailability);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setAvailability(baselineAvailability);
  }, [baselineAvailability, playerId]);

  useEffect(() => {
    if (!leagueId || !playerId || leagueId === 'demo-league') {
      setShadow(null);
      return;
    }
    let active = true;
    setLoading(true);
    api.playerShadow(leagueId, playerId).then((result) => {
      if (!active) return;
      setShadow(result);
      setError(null);
    }).catch((reason) => {
      if (!active) return;
      setShadow(null);
      setError(reason instanceof Error ? reason.message : 'Shadow lab unavailable.');
    }).finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [leagueId, playerId]);

  useEffect(() => {
    if (!leagueId || !playerId || leagueId === 'demo-league') {
      setScenario(null);
      return;
    }
    const timer = window.setTimeout(() => {
      api.playerScenario(leagueId, playerId, {
        role_multiplier: role,
        team_volume_multiplier: volume,
        ...(availability == null ? {} : { availability_probability: availability }),
      }).then((result) => setScenario(result)).catch(() => setScenario(null));
    }, 140);
    return () => window.clearTimeout(timer);
  }, [availability, leagueId, playerId, role, volume]);

  const comparison = shadow?.comparison;
  const contract = comparison?.scoring_contract;
  const decisionComparable = comparison?.decision_comparable ?? false;
  const productionScenario = scenario?.production;
  const challengerScenario = scenario?.challenger;
  const availabilityValue = availability ?? baselineAvailability ?? 1;
  const graphAvailable = shadow?.graph_health.available ?? false;

  const headline = useMemo(() => {
    if (!graphAvailable) return 'No mounted Player State Graph run';
    if (!comparison?.available) return 'No graph state for this player';
    if (!decisionComparable) return 'Research values exist, but scoring is not comparable';
    const delta = comparison.disagreement?.median_delta;
    if (delta == null) return 'Comparable graph forecast available';
    if (Math.abs(delta) < 0.5) return 'Champion and challenger are closely aligned';
    return delta > 0 ? 'Graph sees more weekly upside' : 'Graph is more conservative than production';
  }, [comparison, decisionComparable, graphAvailable]);

  return <section className="panel shadow-lab-panel">
    <div className="panel-heading shadow-heading"><div><span className="eyebrow">Research shadow laboratory</span><h2>Direct model vs. Player State Graph</h2><p>Stress assumptions, inspect disagreement, and audit shared team opportunity without allowing the challenger to silently change a production decision.</p></div><div className={`shadow-status ${decisionComparable ? 'comparable' : 'guarded'}`}><FlaskConical size={17}/><span>{decisionComparable ? 'Comparable shadow' : 'Guarded research'}</span></div></div>

    {loading && <div className="shadow-loading"><RefreshCw size={16} className="spin"/><span>Reading mounted graph artifacts…</span></div>}
    {error && <div className="shadow-warning"><AlertTriangle size={16}/><span>{error}</span></div>}

    <div className="shadow-headline"><GitCompareArrows size={19}/><div><strong>{headline}</strong><span>{contract?.note ?? 'Graph artifact availability is independent from the production projection.'}</span></div></div>

    <div className="shadow-distribution-grid">
      <article><span>Production · authoritative</span><div><b>{metric(comparison?.production?.q10)}</b><strong>{metric(comparison?.production?.q50)}</strong><b>{metric(comparison?.production?.q90)}</b></div><small>weekly q10 / q50 / q90</small></article>
      <article className="challenger"><span>State Graph · research</span><div><b>{metric(comparison?.challenger?.q10)}</b><strong>{metric(comparison?.challenger?.q50)}</strong><b>{metric(comparison?.challenger?.q90)}</b></div><small>{comparison?.available ? `median Δ ${signed(comparison.disagreement?.median_delta)} · overlap ${pct(comparison.disagreement?.interval_overlap_ratio)}` : comparison?.reason?.replaceAll('_', ' ') ?? 'artifact unavailable'}</small></article>
      <article className="contract"><span>Decision comparability</span><strong>{decisionComparable ? 'YES' : 'NO'}</strong><small>{contract?.status?.replaceAll('_', ' ') ?? 'contract unavailable'}</small></article>
    </div>

    <div className="shadow-scenario-shell">
      <div className="scenario-controls">
        <div className="scenario-title"><SlidersHorizontal size={17}/><div><strong>Counterfactual sensitivity</strong><span>These are explicit stress assumptions, not inferred news or calibrated forecasts.</span></div></div>
        <label><div><span>Role / opportunity</span><b>{Math.round((role - 1) * 100) >= 0 ? '+' : ''}{Math.round((role - 1) * 100)}%</b></div><input type="range" min="0.5" max="1.5" step="0.05" value={role} onChange={(event) => setRole(Number(event.target.value))}/></label>
        <label><div><span>Team play volume</span><b>{Math.round((volume - 1) * 100) >= 0 ? '+' : ''}{Math.round((volume - 1) * 100)}%</b></div><input type="range" min="0.75" max="1.25" step="0.025" value={volume} onChange={(event) => setVolume(Number(event.target.value))}/></label>
        <label><div><span>Availability assumption</span><b>{pct(availabilityValue)}</b></div><input type="range" min="0" max="1" step="0.05" value={availabilityValue} onChange={(event) => setAvailability(Number(event.target.value))}/></label>
        <button onClick={() => { setRole(1); setVolume(1); setAvailability(baselineAvailability); }}>Reset assumptions</button>
      </div>
      <div className="scenario-results">
        <div><span>Production stressed median</span><strong>{metric(productionScenario?.scenario.q50)}</strong><small>{signed(productionScenario?.median_delta)} vs baseline · width factor {metric(productionScenario?.uncertainty_factor, 2)}</small></div>
        <div><span>Graph stressed median</span><strong>{metric(challengerScenario?.scenario.q50)}</strong><small>{challengerScenario ? `${signed(challengerScenario.median_delta)} vs graph baseline` : 'graph scenario unavailable'}</small></div>
        <p>{scenario?.authority.note ?? 'Sensitivity results will appear when the server contract is available.'}</p>
      </div>
    </div>

    <div className="opportunity-audit-shell">
      <div className="opportunity-audit-head"><div><span className="eyebrow">Shared team world</span><h3>Opportunity conservation</h3></div><small>{shadow?.opportunity.available ? `${shadow.opportunity.team ?? 'team'} · ${shadow.opportunity.season ?? '—'} W${shadow.opportunity.week ?? '—'}` : shadow?.opportunity.reason?.replaceAll('_', ' ') ?? 'graph role state unavailable'}</small></div>
      {shadow?.opportunity.available ? <>
        <OpportunityBar label="Target share" family={shadow.opportunity.target_share} playerId={playerId}/>
        <OpportunityBar label="Carry share" family={shadow.opportunity.carry_share} playerId={playerId}/>
        <p className="opportunity-note">{shadow.opportunity.note}</p>
      </> : <div className="shadow-empty"><AlertTriangle size={16}/><span>No team-week role artifact exists for this player yet. Nothing is fabricated.</span></div>}
    </div>
  </section>;
}
