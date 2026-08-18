import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle, CheckCircle2, Clock3, RefreshCw, Search, ShieldCheck, Target,
  UsersRound, X, Zap,
} from 'lucide-react';
import type {
  DraftBoardPlayer, DraftBoardResponse, DraftCompareCandidate, DraftCompareResponse,
  DraftLeagueSummary,
} from '../../shared/draft-types';
import { draftApi, DraftApiError } from '../lib/draftApi';
import { Copilot } from './Copilot';
import '../draft-war-room.css';

const ACTIVE = new Set(['pre_draft', 'drafting', 'in_progress']);
const POSITIONS = ['ALL', 'QB', 'RB', 'WR', 'TE'];

function num(value: number | null | undefined, digits = 1) {
  return value == null || !Number.isFinite(value) ? '—' : value.toFixed(digits);
}

function pct(value: number | null | undefined) {
  return value == null || !Number.isFinite(value) ? '—' : `${Math.round(value * 100)}%`;
}

function q50(player: DraftBoardPlayer) {
  return player.season_points_q50 ?? player.fantasy_points_ppr_q50 ?? player.decision_specific_score;
}

function errorDetail(error: unknown) {
  if (error instanceof DraftApiError) {
    const body = error.body as { detail?: { code?: string; message?: string } | string } | undefined;
    if (typeof body?.detail === 'string') return { message: body.detail, code: undefined };
    return { message: body?.detail?.message ?? error.message, code: body?.detail?.code };
  }
  return { message: error instanceof Error ? error.message : 'Draft data unavailable', code: undefined };
}

function winnerName(compare: DraftCompareResponse | null, id: string | null | undefined) {
  if (!id || !compare) return '—';
  return compare.candidates.find((candidate) => candidate.player_id === id)?.player_name ?? id;
}

export function DraftWarRoom({ onOpenConsole }: { onOpenConsole: () => void }) {
  const [leagues, setLeagues] = useState<DraftLeagueSummary[]>([]);
  const [leagueId, setLeagueId] = useState('');
  const [rosterId, setRosterId] = useState('');
  const [draftSlot, setDraftSlot] = useState<number | undefined>();
  const [slotDraft, setSlotDraft] = useState('');
  const [board, setBoard] = useState<DraftBoardResponse | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [comparison, setComparison] = useState<DraftCompareResponse | null>(null);
  const [search, setSearch] = useState('');
  const [position, setPosition] = useState('ALL');
  const [loading, setLoading] = useState(false);
  const [compareLoading, setCompareLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [needsSlot, setNeedsSlot] = useState(false);
  const [lastSuccessAt, setLastSuccessAt] = useState<Date | null>(null);
  const failures = useRef(0);
  const activeRequest = useRef<AbortController | null>(null);
  const compareRequest = useRef<AbortController | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    draftApi.leagues(controller.signal).then((items) => {
      setLeagues(items);
      const first = items[0];
      if (first) {
        setLeagueId((value) => value || first.league_id);
        setRosterId((value) => value || first.external_roster_id || first.rosters?.[0]?.roster_id || '');
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
    const preferred = selectedLeague.external_roster_id || selectedLeague.rosters?.[0]?.roster_id || '';
    setRosterId(preferred);
    setDraftSlot(undefined);
    setSlotDraft('');
    setSelected([]);
    setComparison(null);
  }, [selectedLeague]);

  const refreshBoard = useCallback(async (force = false) => {
    if (!leagueId || !rosterId) return;
    activeRequest.current?.abort();
    const controller = new AbortController();
    activeRequest.current = controller;
    setLoading(true);
    try {
      const payload = await draftApi.board(leagueId, rosterId, {
        draftSlot,
        refresh: true,
        forceRefresh: force,
        signal: controller.signal,
      });
      setBoard(payload);
      setNeedsSlot(false);
      setError(payload.refresh_warning ?? null);
      setLastSuccessAt(new Date());
      failures.current = 0;
      setSelected((ids) => ids.filter((id) => payload.board.some((player) => player.player_id === id)));
    } catch (reason) {
      if (controller.signal.aborted) return;
      const detail = errorDetail(reason);
      setNeedsSlot(detail.code === 'draft_slot_required');
      setError(detail.message);
      failures.current += 1;
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, [draftSlot, leagueId, rosterId]);

  useEffect(() => {
    void refreshBoard(false);
    return () => activeRequest.current?.abort();
  }, [refreshBoard]);

  useEffect(() => {
    if (!board || !ACTIVE.has(board.draft_state.status.toLowerCase())) return;
    const interval = Math.min(30_000, 8_000 * Math.max(1, failures.current + 1));
    const timer = window.setTimeout(() => void refreshBoard(false), interval);
    return () => window.clearTimeout(timer);
  }, [board, lastSuccessAt, refreshBoard]);

  useEffect(() => {
    if (selected.length < 2 || !leagueId || !rosterId) {
      setComparison(null);
      return;
    }
    compareRequest.current?.abort();
    const controller = new AbortController();
    compareRequest.current = controller;
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
    }, 180);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [draftSlot, leagueId, rosterId, selected]);

  const visible = useMemo(() => {
    const term = search.trim().toLowerCase();
    return (board?.board ?? []).filter((player) => {
      if (position !== 'ALL' && player.position !== position) return false;
      if (!term) return true;
      return `${player.player_name} ${player.position} ${player.nfl_team ?? player.recent_team ?? ''}`.toLowerCase().includes(term);
    });
  }, [board, position, search]);

  const compareById = useMemo(
    () => new Map((comparison?.candidates ?? []).map((candidate) => [candidate.player_id, candidate])),
    [comparison],
  );

  function togglePlayer(playerId: string) {
    setSelected((current) => {
      if (current.includes(playerId)) return current.filter((id) => id !== playerId);
      return [...current.slice(-4), playerId];
    });
  }

  function applyDraftSlot() {
    const parsed = Number(slotDraft);
    if (!Number.isInteger(parsed) || parsed < 1 || parsed > Number(selectedLeague?.rosters?.length || board?.league.teams || 32)) {
      setError('Enter a valid draft slot for this league.');
      return;
    }
    setDraftSlot(parsed);
    setNeedsSlot(false);
  }

  const modelSource = board?.survival_model.source ?? 'normal_adp_fallback';
  const empirical = modelSource === 'empirical';

  return <div className="war-room-shell">
    <header className="war-topbar">
      <div className="war-brand"><div className="war-mark">4D</div><div><span>FOURTH DOWN LAB</span><strong>Draft War Room</strong></div></div>
      <div className="war-switchers">
        <label>League<select value={leagueId} onChange={(event) => setLeagueId(event.target.value)}>
          {leagues.map((league) => <option value={league.league_id} key={league.league_id}>{league.name}</option>)}
        </select></label>
        <label>Team<select value={rosterId} onChange={(event) => setRosterId(event.target.value)}>
          {(selectedLeague?.rosters ?? []).map((roster) => <option value={roster.roster_id} key={roster.roster_id}>{roster.team_name}</option>)}
        </select></label>
      </div>
      <div className="war-status">
        <span className={`live-pill ${board?.is_stale ? 'stale' : ''}`}>{board?.is_stale ? 'STALE' : board ? 'LIVE' : 'CONNECTING'}</span>
        <strong>{board?.league.format_label ?? 'League settings loading'}</strong>
        <span>Pick {board?.draft_state.current_pick ?? '—'} · Next {board?.draft_state.next_pick ?? '—'}</span>
      </div>
      <div className="war-actions">
        <button onClick={() => void refreshBoard(true)} disabled={loading}><RefreshCw size={16} className={loading ? 'spin' : ''}/>Refresh</button>
        <Copilot leagueId={leagueId || undefined} rosterId={rosterId || undefined}/>
        <button className="ghost" onClick={onOpenConsole}>Full console</button>
      </div>
    </header>

    {(error || board?.refresh_warning) && <div className="war-warning"><AlertTriangle size={16}/><span>{error ?? board?.refresh_warning}</span></div>}
    {needsSlot && <div className="slot-gate"><div><strong>Draft slot needed</strong><span>The platform snapshot has not exposed your draft order yet. Enter it once and the snake-turn calculations take over.</span></div><input inputMode="numeric" value={slotDraft} onChange={(event) => setSlotDraft(event.target.value)} placeholder="e.g. 5"/><button onClick={applyDraftSlot}>Apply slot</button></div>}

    <section className="decision-strip">
      {(board?.board ?? []).slice(0, 3).map((player, index) => <article key={player.player_id} onClick={() => togglePlayer(player.player_id)}>
        <span>#{index + 1} {player.draft_action}</span><strong>{player.player_name}</strong><small>{player.position} · score {num(player.live_draft_score)} · VORP {num(player.vorp)} · returns {pct(player.survival_to_next_pick)}</small>
      </article>)}
      {!board && <article className="loading-card"><RefreshCw className="spin"/>Loading live room…</article>}
    </section>

    <div className="war-grid">
      <aside className="war-panel roster-rail">
        <div className="war-heading"><div><span>MY TEAM</span><h2>Roster construction</h2></div><ShieldCheck size={18}/></div>
        {['QB', 'RB', 'WR', 'TE'].map((pos) => {
          const players = (board?.roster ?? []).filter((player) => player.position === pos);
          const target = board?.league.roster_slots[pos] ?? 0;
          return <div className="roster-group" key={pos}><div><strong>{pos}</strong><span>{players.length}/{target} direct seats</span></div>{players.map((player) => <p key={player.player_id}>{player.player_name}<small>{num(q50(player))} q50</small></p>)}{!players.length && <p className="empty-roster">Open starter/depth</p>}</div>;
        })}
      </aside>

      <main className="war-panel player-board">
        <div className="board-tools"><div className="search-box"><Search size={16}/><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search available players"/></div><div className="position-tabs">{POSITIONS.map((pos) => <button className={position === pos ? 'active' : ''} onClick={() => setPosition(pos)} key={pos}>{pos}</button>)}</div></div>
        <div className="draft-table-wrap"><table className="draft-table"><thead><tr><th>#</th><th>Player</th><th>Action</th><th>Live</th><th>q10 / q50 / q90</th><th>VORP</th><th>Need</th><th>Tier</th><th>ADP</th><th>Returns</th></tr></thead><tbody>{visible.map((player) => {
          const checked = selected.includes(player.player_id);
          return <tr key={player.player_id} className={checked ? 'selected' : ''} onClick={() => togglePlayer(player.player_id)}>
            <td>{player.live_rank}</td><td><div className="player-cell"><button aria-label={`Compare ${player.player_name}`}>{checked ? <CheckCircle2 size={17}/> : <span/>}</button><div><strong>{player.player_name}</strong><small>{player.position} · {player.nfl_team ?? player.recent_team ?? 'FA'}</small></div></div></td>
            <td><span className={`action ${player.draft_action.toLowerCase().replaceAll(' ', '-')}`}>{player.draft_action}</span></td><td><b>{num(player.live_draft_score)}</b></td><td>{num(player.season_points_q10 ?? player.fantasy_points_ppr_q10, 0)} / <b>{num(q50(player), 0)}</b> / {num(player.season_points_q90 ?? player.fantasy_points_ppr_q90, 0)}</td><td>{num(player.vorp)}</td><td>{pct(player.roster_need_score)}</td><td>{pct(player.tier_cliff_percentile)}</td><td>{num(player.market_adp)}</td><td><strong className={(player.survival_to_next_pick ?? 1) < .35 ? 'danger' : ''}>{pct(player.survival_to_next_pick)}</strong></td>
          </tr>;
        })}</tbody></table></div>
      </main>

      <aside className="war-panel room-rail">
        <div className="war-heading"><div><span>ROOM STATE</span><h2>What is moving</h2></div><UsersRound size={18}/></div>
        <div className="room-metrics"><div><span>Draft slot</span><strong>{board?.draft_state.draft_slot ?? draftSlot ?? '—'}</strong></div><div><span>Until next</span><strong>{board?.draft_state.next_pick ? board.draft_state.next_pick - board.draft_state.current_pick : '—'}</strong></div></div>
        <h3>Last 12 picks</h3><div className="run-grid">{Object.entries(board?.draft_state.recent_position_runs ?? {}).map(([pos, count]) => <span key={pos}><b>{count}</b>{pos}</span>)}</div>
        <h3>Recent picks</h3><div className="recent-picks">{[...(board?.recent_picks ?? [])].reverse().slice(0, 10).map((pick) => <div key={`${pick.pick_no}-${pick.player_id}`}><span>{pick.pick_no}</span><strong>{pick.player_name ?? pick.player_id}</strong><small>{pick.position ?? ''}</small></div>)}</div>
        <div className="market-model"><Target size={17}/><div><strong>{empirical ? 'Empirical room model' : 'Transparent ADP fallback'}</strong><small>{empirical ? `${board?.survival_model.drafts ?? 0} training drafts · Brier ${num(Number(board?.survival_model.metrics?.brier), 3)}` : board?.survival_model.promotion_reason ?? 'No promoted artifact is installed.'}</small></div></div>
        <div className="freshness"><Clock3 size={15}/>Snapshot {num(board?.snapshot_age_seconds, 0)}s old · projection artifact {num(board?.projection_age_seconds, 0)}s old</div>
      </aside>
    </div>

    {selected.length > 0 && <section className="compare-drawer">
      <div className="compare-head"><div><span>COMPARE TRAY · {selected.length}/5</span><h2>{selected.length < 2 ? 'Select one more player' : compareLoading ? 'Simulating roster counterfactuals…' : 'What each pick changes'}</h2></div><button onClick={() => setSelected([])}><X size={16}/>Clear</button></div>
      {comparison && <div className="winner-row"><div><span>Best raw projection</span><strong>{winnerName(comparison, comparison.winners.best_raw_projection)}</strong></div><div><span>Best league value</span><strong>{winnerName(comparison, comparison.winners.best_league_value)}</strong></div><div><span>Best roster fit</span><strong>{winnerName(comparison, comparison.winners.best_roster_fit)}</strong></div><div className="winner"><span>Best pick now</span><strong>{winnerName(comparison, comparison.winners.best_pick_now)}</strong></div></div>}
      <div className="compare-grid">{selected.map((playerId) => {
        const base = board?.board.find((player) => player.player_id === playerId);
        const candidate = compareById.get(playerId) ?? (base as DraftCompareCandidate | undefined);
        if (!candidate) return null;
        const impact = candidate.roster_impact;
        return <article className={comparison?.winners.best_pick_now === playerId ? 'best' : ''} key={playerId}><div className="compare-title"><div><span>{candidate.position}</span><h3>{candidate.player_name}</h3></div><strong>{num(candidate.live_draft_score)}</strong></div>
          <section><h4>Football</h4><p><span>q50</span><b>{num(q50(candidate), 0)}</b></p><p><span>Availability</span><b>{pct(candidate.availability_probability)}</b></p><p><span>Opportunity</span><b>{pct(candidate.opportunity_confidence)}</b></p></section>
          <section><h4>League value</h4><p><span>VORP</span><b>{num(candidate.vorp)}</b></p><p><span>Replacement rank</span><b>{candidate.replacement_rank ?? '—'}</b></p><p><span>Tier cliff</span><b>{pct(candidate.tier_cliff_percentile)}</b></p></section>
          <section><h4>Roster fit</h4><p><span>Fit score</span><b>{num(impact?.roster_fit_score)}</b></p><p><span>Starter slot</span><b>{impact?.projected_slot ?? 'Bench/depth'}</b></p><p><span>Median lineup gain</span><b>+{num(impact?.marginal_median)}</b></p><p><span>Starts in sims</span><b>{pct(impact?.starter_probability)}</b></p></section>
          <section><h4>Timing</h4><p><span>ADP</span><b>{num(candidate.market_adp)}</b></p><p><span>Returns next pick</span><b>{pct(candidate.survival_to_next_pick)}</b></p><p><span>Reach rounds</span><b>{num(candidate.reach_rounds, 2)}</b></p></section>
          <footer><Zap size={15}/>{candidate.draft_reasons ?? candidate.draft_action}</footer>
        </article>;
      })}</div>
    </section>}
  </div>;
}
