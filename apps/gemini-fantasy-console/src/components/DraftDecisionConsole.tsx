import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle, ArrowRight, BarChart3, CheckCircle2, ChevronDown, ChevronUp, Clock3,
  Gauge, Layers3, RefreshCw, Search, ShieldCheck, Sparkles, Target, TrendingUp,
  UsersRound, X, Zap,
} from 'lucide-react';
import {
  CartesianGrid, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis,
} from 'recharts';
import type {
  DraftBoardPlayer, DraftCompareCandidate, DraftCompareResponse, DraftLeagueSummary,
  DraftPlanResponse, RankingAuditResponse,
} from '../../shared/draft-types';
import {
  draftApi, DraftApiError, type ReliableDraftBoardResponse, type ReliableDraftPlayer,
} from '../lib/draftApi';
import { Copilot } from './Copilot';
import '../decision-console.css';
import '../draft-qualification.css';

const ACTIVE = new Set(['pre_draft', 'drafting', 'in_progress']);
const POSITIONS = ['ALL', 'QB', 'RB', 'WR', 'TE'];

function num(value: number | null | undefined, digits = 1) {
  return value == null || !Number.isFinite(value) ? '—' : value.toFixed(digits);
}

function pct(value: number | null | undefined) {
  return value == null || !Number.isFinite(value) ? '—' : `${Math.round(value * 100)}%`;
}

function q10(player: DraftBoardPlayer) {
  return player.valuation_points_q10 ?? player.season_points_q10 ?? player.fantasy_points_ppr_q10;
}

function q50(player: DraftBoardPlayer) {
  return player.valuation_points_q50 ?? player.season_points_q50
    ?? player.fantasy_points_ppr_q50 ?? player.decision_specific_score;
}

function q90(player: DraftBoardPlayer) {
  return player.valuation_points_q90 ?? player.season_points_q90 ?? player.fantasy_points_ppr_q90;
}

function actionFor(player: ReliableDraftPlayer) {
  return player.guarded_draft_action ?? player.draft_action ?? 'CONSIDER';
}

function returnProbability(player: ReliableDraftPlayer) {
  return player.room_survival_to_next_pick ?? player.survival_to_next_pick;
}

function errorDetail(error: unknown) {
  if (error instanceof DraftApiError) {
    const body = error.body as { detail?: { code?: string; message?: string } | string } | undefined;
    if (typeof body?.detail === 'string') return { message: body.detail, code: undefined };
    return { message: body?.detail?.message ?? error.message, code: body?.detail?.code };
  }
  return { message: error instanceof Error ? error.message : 'Draft data unavailable', code: undefined };
}

function ProjectionRange({ player }: { player: DraftBoardPlayer }) {
  const low = q10(player);
  const mid = q50(player);
  const high = q90(player);
  if (low == null || mid == null || high == null || high <= 0) return <span className="muted">—</span>;
  const left = Math.max(0, Math.min(92, (low / high) * 92));
  const marker = Math.max(2, Math.min(98, (mid / high) * 98));
  return <div className="projection-range" title={`${num(low, 0)} / ${num(mid, 0)} / ${num(high, 0)}`}>
    <div className="projection-track">
      <span style={{ left: `${left}%`, width: `${Math.max(4, 96 - left)}%` }}/>
      <i style={{ left: `${marker}%` }}/>
    </div>
    <small>{num(low, 0)} <b>{num(mid, 0)}</b> {num(high, 0)}</small>
  </div>;
}

function ConfidenceRing({ value }: { value: number | null | undefined }) {
  const score = value == null || !Number.isFinite(value) ? 0 : Math.max(0, Math.min(100, value));
  return <div className="confidence-ring" style={{ '--confidence': `${score}%` } as React.CSSProperties}>
    <div><strong>{value == null ? '—' : Math.round(score)}</strong><small>trust</small></div>
  </div>;
}

function DetailMetric({ label, value, note }: { label: string; value: string; note?: string }) {
  return <div className="detail-metric"><span>{label}</span><strong>{value}</strong>{note && <small>{note}</small>}</div>;
}

function actionClass(action: string) {
  return action.toLowerCase().replaceAll(' ', '-');
}

function reasonLabel(reason: string) {
  return reason.toLowerCase().replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function DraftDecisionConsole({ onOpenConsole }: { onOpenConsole: () => void }) {
  const [leagues, setLeagues] = useState<DraftLeagueSummary[]>([]);
  const [leagueId, setLeagueId] = useState('');
  const [rosterId, setRosterId] = useState('');
  const [draftSlot, setDraftSlot] = useState<number | undefined>();
  const [slotDraft, setSlotDraft] = useState('');
  const [board, setBoard] = useState<ReliableDraftBoardResponse | null>(null);
  const [rankingAudit, setRankingAudit] = useState<RankingAuditResponse | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [comparison, setComparison] = useState<DraftCompareResponse | null>(null);
  const [plan, setPlan] = useState<DraftPlanResponse | null>(null);
  const [search, setSearch] = useState('');
  const [position, setPosition] = useState('ALL');
  const [advanced, setAdvanced] = useState(false);
  const [loading, setLoading] = useState(false);
  const [compareLoading, setCompareLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [needsSlot, setNeedsSlot] = useState(false);
  const [reliabilityAvailable, setReliabilityAvailable] = useState(true);
  const [lastSuccessAt, setLastSuccessAt] = useState<Date | null>(null);
  const boardRequest = useRef<AbortController | null>(null);
  const auditRequest = useRef<AbortController | null>(null);
  const compareRequest = useRef<AbortController | null>(null);
  const planRequest = useRef<AbortController | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    draftApi.leagues(controller.signal).then((items) => {
      setLeagues(items);
      const first = items[0];
      if (first) {
        setLeagueId(first.league_id);
        setRosterId(first.external_roster_id || first.rosters?.[0]?.roster_id || '');
      }
    }).catch((reason) => setError(errorDetail(reason).message));
    return () => controller.abort();
  }, []);

  const selectedLeague = useMemo(
    () => leagues.find((league) => league.league_id === leagueId),
    [leagueId, leagues],
  );

  useEffect(() => {
    if (!selectedLeague) return;
    setRosterId(selectedLeague.external_roster_id || selectedLeague.rosters?.[0]?.roster_id || '');
    setDraftSlot(undefined);
    setSlotDraft('');
    setSelected([]);
    setComparison(null);
    setPlan(null);
  }, [selectedLeague]);

  const refreshAudit = useCallback(async () => {
    if (!leagueId) return;
    auditRequest.current?.abort();
    const controller = new AbortController();
    auditRequest.current = controller;
    try {
      setRankingAudit(await draftApi.rankingAudit(leagueId, controller.signal));
    } catch (reason) {
      if (!controller.signal.aborted) setError(errorDetail(reason).message);
    }
  }, [leagueId]);

  const refreshBoard = useCallback(async (force = false) => {
    if (!leagueId || !rosterId) return;
    boardRequest.current?.abort();
    const controller = new AbortController();
    boardRequest.current = controller;
    setLoading(true);
    try {
      let payload: ReliableDraftBoardResponse;
      try {
        payload = await draftApi.reliableBoard(leagueId, rosterId, {
          draftSlot,
          refresh: true,
          forceRefresh: force,
          roomSimulations: 600,
          signal: controller.signal,
        });
        setReliabilityAvailable(true);
      } catch (reason) {
        if (controller.signal.aborted) return;
        if (!(reason instanceof DraftApiError) || reason.status !== 404) throw reason;
        const fallback = await draftApi.board(leagueId, rosterId, {
          draftSlot,
          refresh: true,
          forceRefresh: force,
          signal: controller.signal,
        });
        payload = fallback as ReliableDraftBoardResponse;
        setReliabilityAvailable(false);
      }
      setBoard(payload);
      setNeedsSlot(false);
      setError(payload.refresh_warning ?? null);
      setLastSuccessAt(new Date());
      setSelected((ids) => ids.filter((id) => payload.board.some((player) => player.player_id === id)));
      void refreshAudit();
    } catch (reason) {
      if (controller.signal.aborted) return;
      const detail = errorDetail(reason);
      setNeedsSlot(detail.code === 'draft_slot_required' || /draft slot/i.test(detail.message));
      setError(detail.message);
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, [draftSlot, leagueId, refreshAudit, rosterId]);

  useEffect(() => {
    void refreshBoard(false);
    return () => {
      boardRequest.current?.abort();
      auditRequest.current?.abort();
    };
  }, [refreshBoard]);

  useEffect(() => {
    if (!board || !ACTIVE.has(board.draft_state.status.toLowerCase())) return;
    const timer = window.setTimeout(() => void refreshBoard(false), 10_000);
    return () => window.clearTimeout(timer);
  }, [board, lastSuccessAt, refreshBoard]);

  useEffect(() => {
    if (selected.length < 2 || !leagueId || !rosterId) {
      setComparison(null);
      setPlan(null);
      return;
    }
    compareRequest.current?.abort();
    planRequest.current?.abort();
    const controller = new AbortController();
    const researchController = new AbortController();
    compareRequest.current = controller;
    planRequest.current = researchController;
    const timer = window.setTimeout(() => {
      setCompareLoading(true);
      draftApi.compare(
        leagueId,
        {
          roster_id: rosterId,
          player_ids: selected,
          draft_slot: draftSlot,
          refresh: false,
          simulations: 600,
        },
        controller.signal,
      ).then(setComparison).catch((reason) => {
        if (!controller.signal.aborted) setError(errorDetail(reason).message);
      }).finally(() => {
        if (!controller.signal.aborted) setCompareLoading(false);
      });
      draftApi.plan(
        leagueId,
        {
          roster_id: rosterId,
          player_ids: selected,
          draft_slot: draftSlot,
          refresh: false,
          simulations: 1500,
        },
        researchController.signal,
      ).then(setPlan).catch(() => {
        if (!researchController.signal.aborted) setPlan(null);
      });
    }, 160);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
      researchController.abort();
    };
  }, [draftSlot, leagueId, rosterId, selected]);

  const visible = useMemo(() => {
    const term = search.trim().toLowerCase();
    return (board?.board ?? []).filter((player) => {
      if (position !== 'ALL' && player.position !== position) return false;
      if (!term) return true;
      return `${player.player_name} ${player.position} ${player.nfl_team ?? player.recent_team ?? ''}`
        .toLowerCase().includes(term);
    });
  }, [board, position, search]);

  const rankingById = useMemo(
    () => new Map((rankingAudit?.rows ?? []).map((row) => [row.player_id, row])),
    [rankingAudit],
  );
  const compareById = useMemo(
    () => new Map((comparison?.candidates ?? []).map((candidate) => [candidate.player_id, candidate])),
    [comparison],
  );
  const planById = useMemo(
    () => new Map((plan?.plans ?? []).map((item) => [item.player_id, item])),
    [plan],
  );

  const recommendation = board?.board[0];
  const qualification = board?.qualification;
  const nextPickDistance = board?.draft_state.next_pick
    ? board.draft_state.next_pick - board.draft_state.current_pick
    : null;
  const scoringExact = rankingAudit?.scoring_status.scoring_exact ?? false;
  const externalSources = rankingAudit?.ranking_context.expert_sources?.length ?? 0;
  const marketData = useMemo(() => (board?.board ?? []).slice(0, 26).map((player) => ({
    playerId: player.player_id,
    name: player.player_name,
    position: player.position,
    returnChance: (returnProbability(player) ?? 0) * 100,
    vorp: player.vorp ?? 0,
    score: player.live_draft_score ?? 0,
  })), [board]);

  function togglePlayer(playerId: string) {
    setSelected((current) => {
      if (current.includes(playerId)) return current.filter((id) => id !== playerId);
      return [...current.slice(-4), playerId];
    });
  }

  function applyDraftSlot() {
    const parsed = Number(slotDraft);
    const upper = Number(selectedLeague?.rosters?.length || board?.league.teams || 32);
    if (!Number.isInteger(parsed) || parsed < 1 || parsed > upper) {
      setError('Enter a valid draft slot for this league.');
      return;
    }
    setDraftSlot(parsed);
    setNeedsSlot(false);
  }

  const qualificationReason = qualification?.blocking_reasons[0]
    ?? qualification?.caution_reasons[0];

  return <div className="decision-console">
    <header className="decision-topbar">
      <div className="decision-brand"><div className="decision-mark">4D</div><div><span>FOURTH DOWN LAB</span><strong>Decision Console</strong></div></div>
      <div className="decision-switchers">
        <label><span>League</span><select value={leagueId} onChange={(event) => setLeagueId(event.target.value)}>
          {leagues.map((league) => <option value={league.league_id} key={league.league_id}>{league.name}</option>)}
        </select></label>
        <label><span>Team</span><select value={rosterId} onChange={(event) => setRosterId(event.target.value)}>
          {(selectedLeague?.rosters ?? []).map((roster) => <option value={roster.roster_id} key={roster.roster_id}>{roster.team_name}</option>)}
        </select></label>
      </div>
      <div className="decision-state">
        <span className={`live-state ${qualification?.status === 'BLOCKED' || board?.is_stale ? 'stale' : qualification?.status === 'CAUTION' ? 'caution' : ''}`}>{qualification?.status ?? (board?.is_stale ? 'STALE' : board ? 'LIVE' : 'CONNECTING')}</span>
        <strong>{board?.league.format_label ?? 'Loading league rules'}</strong>
        <small>Pick {board?.draft_state.current_pick ?? '—'} · next {board?.draft_state.next_pick ?? '—'}</small>
      </div>
      <div className="decision-actions">
        <button onClick={() => void refreshBoard(true)} disabled={loading}><RefreshCw size={15} className={loading ? 'spin' : ''}/>Refresh</button>
        <Copilot leagueId={leagueId || undefined} rosterId={rosterId || undefined}/>
        <button className="secondary" onClick={onOpenConsole}>Season console</button>
      </div>
    </header>

    {error && <div className="decision-warning"><AlertTriangle size={16}/><span>{error}</span></div>}
    {!reliabilityAvailable && board && <div className="decision-warning soft"><ShieldCheck size={16}/><span>The reliable-board API is not available on this deployment yet. Showing the authoritative baseline board without the independent room-confidence layer.</span></div>}
    {needsSlot && <div className="decision-slot-gate"><div><strong>Where are you drafting?</strong><span>Enter your slot once. Snake-turn timing and return probabilities will update automatically.</span></div><input inputMode="numeric" value={slotDraft} onChange={(event) => setSlotDraft(event.target.value)} placeholder="5"/><button onClick={applyDraftSlot}>Use slot</button></div>}

    <section className="decision-hero">
      <div className="hero-main">
        <div className="hero-kicker"><Sparkles size={15}/><span>Best decision right now</span></div>
        {recommendation ? <>
          <div className="hero-player-line"><div><span className={`position-chip ${recommendation.position.toLowerCase()}`}>{recommendation.position}</span><h1>{recommendation.player_name}</h1><p>{recommendation.nfl_team ?? recommendation.recent_team ?? 'Free agent'} · rank #{recommendation.live_rank}</p></div><span className={`hero-action ${actionClass(actionFor(recommendation))}`}>{actionFor(recommendation)}</span></div>
          <div className="hero-metrics">
            <DetailMetric label="Decision score" value={num(recommendation.live_draft_score)} note="authoritative board"/>
            <DetailMetric label="League VORP" value={num(recommendation.vorp)} note="replacement adjusted"/>
            <DetailMetric label="Returns next turn" value={pct(returnProbability(recommendation))} note="room survival"/>
            <DetailMetric label="Wait cost" value={num(recommendation.room_position_wait_loss ?? recommendation.position_wait_loss)} note="same-position value"/>
          </div>
          <div className="hero-range"><span>Projected range</span><ProjectionRange player={recommendation}/></div>
          <p className="hero-reason">{recommendation.draft_reliability_reasons ?? recommendation.draft_reasons ?? 'League-adjusted value, roster fit, scarcity, and market timing drive this recommendation.'}</p>
        </> : <div className="hero-loading"><RefreshCw className="spin"/><strong>Building your live board</strong><span>Reading league rules, roster state, projections, and room timing.</span></div>}
      </div>
      <aside className="hero-trust">
        <ConfidenceRing value={recommendation?.draft_reliability_score}/>
        <div className="trust-copy"><span>Decision confidence</span><strong>{recommendation?.draft_reliability ?? (reliabilityAvailable ? 'CALCULATING' : 'BASELINE')}</strong><small>{recommendation?.projection_freshness_status ? `Projection data ${recommendation.projection_freshness_status.toLowerCase()}` : 'Confidence stays separate from player quality.'}</small></div>
        <div className="turn-card"><div><Clock3 size={15}/><span>Next decision window</span></div><strong>{nextPickDistance == null ? '—' : `${nextPickDistance} picks`}</strong><small>{board?.draft_state.next_pick ? `Your next turn is pick ${board.draft_state.next_pick}.` : 'Turn timing unavailable.'}</small></div>
        <div className={`readiness-card ${qualification?.status.toLowerCase() ?? ''}`}><div><Gauge size={15}/><span>{qualification ? 'Draft qualification' : 'League readiness'}</span></div><strong>{qualification?.status ?? (board?.readiness ? Math.round(board.readiness.score) : '—')}</strong><small>{qualification ? (qualificationReason ? reasonLabel(qualificationReason) : `Inputs ${Math.round(qualification.readiness_score)} · projections and room state fresh.`) : board?.readiness?.ready ? 'Core inputs ready for decisions.' : board?.readiness?.flags?.slice(0, 2).join(' · ') || 'Readiness audit unavailable.'}</small></div>
      </aside>
    </section>

    <section className="decision-shortlist">
      <div className="section-heading"><div><span>SHORTLIST</span><h2>Your next three moves</h2></div><small>Click cards to compare complete roster impact.</small></div>
      <div className="shortlist-grid">{(board?.board ?? []).slice(0, 3).map((player, index) => <button className={selected.includes(player.player_id) ? 'selected' : ''} key={player.player_id} onClick={() => togglePlayer(player.player_id)}>
        <div className="shortlist-rank">0{index + 1}</div><div className="shortlist-player"><span>{player.position} · {player.nfl_team ?? player.recent_team ?? 'FA'}</span><strong>{player.player_name}</strong><small>{actionFor(player)} · {player.draft_reliability_reasons ?? player.draft_reasons ?? 'league fit + market timing'}</small></div><div className="shortlist-value"><strong>{num(player.live_draft_score)}</strong><small>{pct(returnProbability(player))} returns</small></div><ArrowRight size={17}/>
      </button>)}</div>
    </section>

    <div className="decision-layout">
      <main className="decision-panel board-panel">
        <div className="section-heading board-heading"><div><span>AVAILABLE PLAYERS</span><h2>Decision board</h2></div><div className="board-controls"><div className="search-control"><Search size={15}/><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search players"/></div><div className="position-control">{POSITIONS.map((pos) => <button className={position === pos ? 'active' : ''} onClick={() => setPosition(pos)} key={pos}>{pos}</button>)}</div><button className="advanced-toggle" onClick={() => setAdvanced((value) => !value)}>{advanced ? <ChevronUp size={15}/> : <ChevronDown size={15}/>}Details</button></div></div>
        <div className="decision-table-wrap"><table className="decision-table"><thead><tr><th>#</th><th>Player</th><th>Signal</th><th>Projection</th><th>VORP</th><th>Wait</th><th>Returns</th><th>Trust</th>{advanced && <><th>ADP</th><th>Expert #</th><th>Δ</th><th>Room #</th></>}</tr></thead><tbody>{visible.map((player) => {
          const checked = selected.includes(player.player_id);
          const audit = rankingById.get(player.player_id);
          return <tr key={player.player_id} className={checked ? 'selected' : ''} onClick={() => togglePlayer(player.player_id)}>
            <td><strong>{player.live_rank}</strong></td>
            <td><div className="decision-player"><span className={`position-dot ${player.position.toLowerCase()}`}/><div><strong>{player.player_name}</strong><small>{player.position} · {player.nfl_team ?? player.recent_team ?? 'FA'}</small></div>{checked && <CheckCircle2 size={16}/>}</div></td>
            <td><span className={`table-action ${actionClass(actionFor(player))}`}>{actionFor(player)}</span></td>
            <td><ProjectionRange player={player}/></td>
            <td><strong>{num(player.vorp)}</strong></td>
            <td>{num(player.room_position_wait_loss ?? player.position_wait_loss)}</td>
            <td><strong className={(returnProbability(player) ?? 1) < 0.35 ? 'hot' : ''}>{pct(returnProbability(player))}</strong></td>
            <td><span className={`trust-pill ${(player.draft_reliability ?? 'baseline').toLowerCase()}`}>{player.draft_reliability_score == null ? 'BASE' : Math.round(player.draft_reliability_score)}</span></td>
            {advanced && <><td>{num(player.market_adp)}</td><td>{num(audit?.external_consensus_rank, 0)}</td><td>{audit?.model_vs_external_rank_delta == null ? '—' : `${audit.model_vs_external_rank_delta > 0 ? '+' : ''}${audit.model_vs_external_rank_delta.toFixed(0)}`}</td><td>{player.room_rank ?? '—'}</td></>}
          </tr>;
        })}</tbody></table></div>
      </main>

      <aside className="decision-side-stack">
        <section className="decision-panel market-map-panel">
          <div className="section-heading compact"><div><span>MARKET MAP</span><h2>Value vs. waitability</h2></div><TrendingUp size={18}/></div>
          <p className="panel-copy">Upper-left is the pressure zone: valuable players unlikely to make it back.</p>
          <div className="market-chart"><ResponsiveContainer width="100%" height={250}><ScatterChart margin={{ top: 12, right: 12, bottom: 6, left: -14 }}><CartesianGrid strokeDasharray="3 3"/><XAxis type="number" dataKey="returnChance" name="Return chance" unit="%" domain={[0, 100]}/><YAxis type="number" dataKey="vorp" name="VORP"/><Tooltip formatter={(value) => typeof value === 'number' ? value.toFixed(1) : value}/><Scatter data={marketData}/></ScatterChart></ResponsiveContainer></div>
          <div className="market-legend"><span><i/>Top {marketData.length} board candidates</span><small>Hover to inspect return probability and VORP.</small></div>
        </section>

        <section className="decision-panel roster-panel">
          <div className="section-heading compact"><div><span>MY BUILD</span><h2>Roster construction</h2></div><Layers3 size={18}/></div>
          <div className="roster-positions">{['QB', 'RB', 'WR', 'TE'].map((pos) => {
            const owned = (board?.roster ?? []).filter((player) => player.position === pos);
            const target = board?.league.roster_slots[pos] ?? 0;
            const open = Math.max(0, target - owned.length);
            return <div key={pos}><div><strong>{pos}</strong><span>{owned.length}/{target}</span></div><div className="seat-track"><i style={{ width: `${target ? Math.min(100, owned.length / target * 100) : 0}%` }}/></div><small>{open ? `${open} direct seat${open === 1 ? '' : 's'} open` : 'direct seats filled'}</small></div>;
          })}</div>
        </section>

        <section className="decision-panel data-panel">
          <div className="section-heading compact"><div><span>TRUST LAYER</span><h2>Can I act on this?</h2></div><ShieldCheck size={18}/></div>
          <div className="data-checks"><div><span>Draft qualification</span><strong className={qualification?.status === 'READY' ? 'ok' : qualification?.status === 'BLOCKED' ? 'bad' : 'warn'}>{qualification?.status ?? 'Unknown'}</strong></div><div><span>Scoring translation</span><strong className={scoringExact ? 'ok' : 'warn'}>{scoringExact ? 'Exact' : 'Partial'}</strong></div><div><span>Projection freshness</span><strong className={recommendation?.projection_freshness_status === 'FRESH' ? 'ok' : 'warn'}>{recommendation?.projection_freshness_status ?? 'Unknown'}</strong></div><div><span>External expert sources</span><strong>{externalSources}</strong></div><div><span>Room challenger</span><strong>{reliabilityAvailable ? 'Shadow only' : 'Unavailable'}</strong></div><div><span>Survival model</span><strong>{board?.survival_model.source === 'empirical' ? 'Empirical' : 'ADP fallback'}</strong></div></div>
          {qualification?.blocking_reasons.length ? <p className="data-flags blocked">{qualification.blocking_reasons.map(reasonLabel).slice(0, 3).join(' · ')}</p> : qualification?.caution_reasons.length ? <p className="data-flags">{qualification.caution_reasons.map(reasonLabel).slice(0, 3).join(' · ')}</p> : board?.readiness?.flags?.length ? <p className="data-flags">{board.readiness.flags.slice(0, 3).join(' · ')}</p> : <p className="data-flags good">No hard readiness flags.</p>}
        </section>

        <section className="decision-panel room-panel">
          <div className="section-heading compact"><div><span>ROOM PULSE</span><h2>What is moving</h2></div><UsersRound size={18}/></div>
          <div className="run-grid">{Object.entries(board?.draft_state.recent_position_runs ?? {}).map(([pos, count]) => <span key={pos}><b>{count}</b>{pos}</span>)}</div>
          <div className="recent-picks">{[...(board?.recent_picks ?? [])].reverse().slice(0, 6).map((pick) => <div key={`${pick.pick_no}-${pick.player_id}`}><span>{pick.pick_no}</span><strong>{pick.player_name ?? pick.player_id}</strong><small>{pick.position ?? ''}</small></div>)}</div>
        </section>
      </aside>
    </div>

    {selected.length > 0 && <section className="decision-compare">
      <div className="compare-heading"><div><span>COMPARE · {selected.length}/5</span><h2>{selected.length < 2 ? 'Pick one more player to run the counterfactual' : compareLoading ? 'Simulating roster outcomes…' : 'Which choice actually helps your team?'}</h2></div><button onClick={() => setSelected([])}><X size={15}/>Clear</button></div>
      {comparison && <div className="compare-winners"><span>Raw projection <b>{comparison.winners.best_raw_projection ? compareById.get(comparison.winners.best_raw_projection)?.player_name : '—'}</b></span><span>Roster fit <b>{comparison.winners.best_roster_fit ? compareById.get(comparison.winners.best_roster_fit)?.player_name : '—'}</b></span><span className="primary">Best pick now <b>{comparison.winners.best_pick_now ? compareById.get(comparison.winners.best_pick_now)?.player_name : '—'}</b></span></div>}
      <div className="compare-cards">{selected.map((playerId) => {
        const base = board?.board.find((player) => player.player_id === playerId);
        const candidate = compareById.get(playerId) ?? (base as DraftCompareCandidate | undefined);
        if (!candidate) return null;
        const research = planById.get(playerId);
        return <article className={comparison?.winners.best_pick_now === playerId ? 'winner' : ''} key={playerId}><header><span>{candidate.position}</span><h3>{candidate.player_name}</h3><strong>{num(candidate.live_draft_score)}</strong></header><div className="compare-metrics"><DetailMetric label="q50" value={num(q50(candidate), 0)}/><DetailMetric label="VORP" value={num(candidate.vorp)}/><DetailMetric label="Lineup gain" value={`+${num(candidate.roster_impact?.marginal_median)}`}/><DetailMetric label="Starts" value={pct(candidate.roster_impact?.starter_probability)}/><DetailMetric label="Returns" value={pct(candidate.survival_to_next_pick)}/><DetailMetric label="2-pick value" value={num(research?.expected_two_pick_value)}/></div><footer><Zap size={14}/>{candidate.draft_reasons ?? candidate.draft_action}</footer></article>;
      })}</div>
    </section>}
  </div>;
}
