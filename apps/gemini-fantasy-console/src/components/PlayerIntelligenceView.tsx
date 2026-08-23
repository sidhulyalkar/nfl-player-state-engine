import { useEffect, useMemo, useState } from 'react';
import {
  Activity, AlertTriangle, Bookmark, BookmarkCheck, ChevronDown, ChevronUp, CircleGauge,
  History, Search, ShieldCheck, Sparkles, Target, TrendingUp,
} from 'lucide-react';
import type {
  DataMode, PlayerIntelligenceResponse, PlayerRow, ResearchPrediction,
} from '../../shared/types';
import { api } from '../lib/api';
import { ModeBadge } from './ModeBadge';
import { ShadowLabPanel } from './ShadowLabPanel';

function metric(value: number | null | undefined, digits = 1) {
  return value == null || !Number.isFinite(value) ? '—' : value.toFixed(digits);
}

function percent(value: number | null | undefined) {
  return value == null || !Number.isFinite(value) ? '—' : `${Math.round(value * 100)}%`;
}

function signed(value: number | null | undefined, digits = 1) {
  if (value == null || !Number.isFinite(value)) return '—';
  return `${value > 0 ? '+' : ''}${value.toFixed(digits)}`;
}

function loadWatchlist() {
  try {
    const raw = window.localStorage.getItem('pse-player-watchlist');
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.map(String) : [];
  } catch {
    return [];
  }
}

function writePlayerRoute(leagueId: string, playerId: string) {
  if (leagueId === 'demo-league' || !playerId) return;
  const url = new URL(window.location.href);
  url.searchParams.set('workspace', 'intelligence');
  url.searchParams.set('league', leagueId);
  url.searchParams.set('player', playerId);
  window.history.replaceState(null, '', url);
}

export function PlayerIntelligenceView({
  leagueId,
  players,
  mode,
  initialPlayerId,
}: {
  leagueId: string;
  players: PlayerRow[];
  mode: DataMode;
  initialPlayerId?: string;
}) {
  const [query, setQuery] = useState('');
  const [selectedId, setSelectedId] = useState(initialPlayerId ?? players[0]?.player_id ?? '');
  const [profile, setProfile] = useState<PlayerIntelligenceResponse | null>(null);
  const [history, setHistory] = useState<ResearchPrediction[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [rawOpen, setRawOpen] = useState(false);
  const [watchlist, setWatchlist] = useState<string[]>(loadWatchlist);

  useEffect(() => {
    if (!players.length) return;
    setSelectedId((current) => {
      const preferred = initialPlayerId
        && players.some((player) => player.player_id === initialPlayerId)
        ? initialPlayerId
        : undefined;
      if (preferred) return preferred;
      if (players.some((player) => player.player_id === current)) return current;
      return players[0]?.player_id ?? '';
    });
  }, [initialPlayerId, leagueId, players]);

  const selectedIsValid = useMemo(
    () => players.some((player) => player.player_id === selectedId),
    [players, selectedId],
  );

  useEffect(() => {
    if (!selectedId || !selectedIsValid || leagueId === 'demo-league') return;
    writePlayerRoute(leagueId, selectedId);
  }, [leagueId, selectedId, selectedIsValid]);

  useEffect(() => {
    if (!selectedId || !selectedIsValid || leagueId === 'demo-league') {
      setProfile(null);
      setHistory([]);
      setLoading(false);
      return;
    }
    let active = true;
    setLoading(true);
    setError(null);
    Promise.allSettled([
      api.playerIntelligence(leagueId, selectedId),
      api.playerHistory(selectedId, 200),
    ]).then(([profileResult, historyResult]) => {
      if (!active) return;
      if (profileResult.status === 'fulfilled') {
        setProfile(profileResult.value);
      } else {
        setProfile(null);
        setError(profileResult.reason instanceof Error ? profileResult.reason.message : 'Player intelligence unavailable.');
      }
      setHistory(historyResult.status === 'fulfilled' ? historyResult.value.predictions ?? [] : []);
    }).finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [leagueId, selectedId, selectedIsValid]);

  const visible = useMemo(() => {
    const term = query.trim().toLowerCase();
    const ordered = [...players].sort((a, b) => {
      const aw = watchlist.includes(a.player_id) ? 1 : 0;
      const bw = watchlist.includes(b.player_id) ? 1 : 0;
      if (aw !== bw) return bw - aw;
      return (a.overall_rank ?? 9999) - (b.overall_rank ?? 9999);
    });
    if (!term) return ordered;
    return ordered.filter((player) => `${player.player_name} ${player.position} ${player.recent_team ?? ''}`.toLowerCase().includes(term));
  }, [players, query, watchlist]);

  function toggleWatchlist(playerId: string) {
    setWatchlist((current) => {
      const next = current.includes(playerId)
        ? current.filter((id) => id !== playerId)
        : [...current, playerId];
      window.localStorage.setItem('pse-player-watchlist', JSON.stringify(next));
      return next;
    });
  }

  const selectedFallback = players.find((player) => player.player_id === selectedId);
  const projection = profile?.projection;
  const playerName = profile?.player.player_name ?? selectedFallback?.player_name ?? 'Select a player';
  const playerPosition = profile?.player.position ?? selectedFallback?.position ?? '—';
  const playerTeam = profile?.player.team ?? selectedFallback?.recent_team ?? '—';
  const watched = selectedId ? watchlist.includes(selectedId) : false;
  const sortedHistory = [...history].sort((a, b) => (b.season - a.season) || (b.week - a.week));
  const baselineAvailability = Number(profile?.raw_model_fields.availability_probability ?? NaN);

  return <div className="intelligence-workspace">
    <aside className="player-browser panel">
      <div className="player-browser-head"><div><span className="eyebrow">Player universe</span><h2>Intelligence explorer</h2></div><ModeBadge mode={mode}/></div>
      <div className="intelligence-search"><Search size={16}/><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search any player"/></div>
      <div className="watch-note"><Bookmark size={14}/><span>{watchlist.length} watched · saved in this browser</span></div>
      <div className="player-browser-list">{visible.slice(0, 180).map((player) => <button key={player.player_id} className={selectedId === player.player_id ? 'active' : ''} onClick={() => setSelectedId(player.player_id)}>
        <span className={`position-tag ${player.position.toLowerCase()}`}>{player.position}</span>
        <div><strong>{player.player_name}</strong><small>{player.recent_team ?? 'FA'} · #{player.overall_rank ?? '—'} current board</small></div>
        {watchlist.includes(player.player_id) && <BookmarkCheck size={15}/>} 
      </button>)}</div>
    </aside>

    <main className="player-intelligence-main">
      {leagueId === 'demo-league' && <section className="panel intelligence-boundary"><AlertTriangle size={18}/><div><strong>Connect a stored league for the full intelligence contract.</strong><span>The bundled visual demo intentionally does not fabricate server-side league calculations.</span></div></section>}
      {error && <section className="panel intelligence-boundary"><AlertTriangle size={18}/><div><strong>Player intelligence unavailable.</strong><span>{error}</span></div></section>}
      <section className="panel player-intelligence-hero">
        <div className="intelligence-identity"><div className="badge-line"><span className={`position-tag ${String(playerPosition).toLowerCase()}`}>{playerPosition}</span><span className="eyebrow">{profile?.authority.production_projection_authoritative ? 'Production projection' : 'Player profile'}</span></div><h1>{playerName}</h1><p>{playerTeam}{profile?.player.owner_team_name ? ` · ${profile.player.owner_team_name}` : profile?.player.is_free_agent ? ' · Free agent' : ''}{profile?.player.age ? ` · age ${profile.player.age}` : ''}</p></div>
        <button className={`watch-button ${watched ? 'active' : ''}`} disabled={!selectedId} onClick={() => selectedId && toggleWatchlist(selectedId)}>{watched ? <BookmarkCheck size={17}/> : <Bookmark size={17}/>} {watched ? 'Watching' : 'Watch player'}</button>
        <div className="projection-fan">
          <div className="projection-fan-label"><span>League projection</span><small>q10 / median / q90</small></div>
          <div className="projection-fan-values"><span>{metric(projection?.q10)}</span><strong>{metric(projection?.q50)}</strong><span>{metric(projection?.q90)}</span></div>
          <div className="projection-fan-track"><i style={{ left: '10%', width: '80%' }}/><b style={{ left: '50%' }}/></div>
          <small>{projection?.relative_interval_width == null ? 'Distribution unavailable' : `${percent(projection.relative_interval_width)} interval width relative to median`}</small>
        </div>
      </section>

      {loading && <section className="panel intelligence-loading"><Activity className="spin" size={18}/><span>Resolving league value, uncertainty, history and decision context…</span></section>}

      {profile && <>
        <div className="intelligence-metric-grid">
          <article><CircleGauge size={18}/><span>Median vs replacement</span><strong>{signed(profile.replacement_margins.q50)}</strong><small>league-specific points margin</small></article>
          <article><ShieldCheck size={18}/><span>Availability</span><strong>{percent(Number(profile.raw_model_fields.availability_probability ?? NaN))}</strong><small>model input, not medical certainty</small></article>
          <article><Target size={18}/><span>Opportunity confidence</span><strong>{percent(Number(profile.raw_model_fields.opportunity_confidence ?? NaN))}</strong><small>role/opportunity support</small></article>
          <article><TrendingUp size={18}/><span>Outcome width</span><strong>{metric(projection?.interval_width)}</strong><small>q90 minus q10</small></article>
        </div>

        {selectedId && <ShadowLabPanel
          leagueId={leagueId}
          playerId={selectedId}
          baselineAvailability={Number.isFinite(baselineAvailability) ? baselineAvailability : undefined}
        />}

        <section className="panel decision-matrix-panel">
          <div className="panel-heading"><div><span className="eyebrow">Rank multiverse</span><h2>Same player, six different decisions</h2><p>Every score below is recomputed server-side from the actual league contract.</p></div><Sparkles size={20}/></div>
          <div className="decision-matrix-grid">{profile.decision_matrix.map((row) => <article key={row.decision}>
            <div><span>{row.decision.replaceAll('_', ' ')}</span><b>#{row.overall_rank ?? '—'}</b></div>
            <strong>{metric(row.score)}</strong>
            <small>{row.position_rank ? `${playerPosition}${row.position_rank} · ` : ''}{row.percentile == null ? '' : `${percent(row.percentile)} percentile`}</small>
            <p>{row.reasons ?? 'Projection-led league value.'}</p>
            <footer><span>VORP {metric(row.vorp)}</span><span>Floor {metric(row.floor_vorp)}</span><span>Upside {metric(row.upside_vorp)}</span></footer>
          </article>)}</div>
        </section>

        <div className="intelligence-two-column">
          <section className="panel signal-panel"><div className="panel-heading"><div><span className="eyebrow">Model inputs</span><h2>What is shaping the player</h2></div><Activity size={19}/></div>
            <div className="signal-list">{profile.signals.length ? profile.signals.map((signal) => <div key={signal.key}><div><strong>{signal.label}</strong><span className={`signal-status ${signal.status}`}>{signal.status}</span></div><div className="signal-track"><i style={{ width: `${Math.max(0, Math.min(100, signal.value * 100))}%` }}/></div><small>{percent(signal.value)}</small></div>) : <p className="muted">No optional signal columns are present in the current production artifact.</p>}</div>
          </section>
          <section className="panel authority-panel"><div className="panel-heading"><div><span className="eyebrow">Authority boundary</span><h2>What can this screen claim?</h2></div><ShieldCheck size={19}/></div>
            <div className="authority-list"><div><span>Direct projection</span><strong>Authoritative</strong></div><div><span>League decision board</span><strong>Authoritative</strong></div><div><span>Player State Graph</span><strong>{profile.authority.player_state_graph_authority.replaceAll('_', ' ')}</strong></div><div><span>Trust score semantics</span><strong>Guardrail only</strong></div></div><p>{profile.authority.note}</p>
          </section>
        </div>

        <section className="panel history-panel"><div className="panel-heading"><div><span className="eyebrow">Frozen out-of-sample replay</span><h2>How this player has behaved against prior forecasts</h2></div><History size={20}/></div>
          {!sortedHistory.length ? <div className="empty-history"><History size={18}/><span>No exact player-ID history exists in the currently mounted frozen benchmark artifact.</span></div> : <div className="table-scroll"><table><thead><tr><th>Game</th><th>Forecast</th><th>Actual</th><th>Median error</th><th>Interval result</th></tr></thead><tbody>{sortedHistory.slice(0, 40).map((row, index) => {
            const inside = row.actual != null && row.q10 != null && row.q90 != null && row.actual >= row.q10 && row.actual <= row.q90;
            return <tr key={`${row.season}-${row.week}-${index}`}><td>{row.season} · W{row.week}</td><td>{metric(row.q10)} / <strong>{metric(row.q50)}</strong> / {metric(row.q90)}</td><td>{metric(row.actual)}</td><td>{row.actual == null || row.q50 == null ? '—' : signed(row.q50 - row.actual)}</td><td><span className={`history-result ${inside ? 'inside' : 'miss'}`}>{inside ? 'Inside 80%' : 'Miss'}</span></td></tr>;
          })}</tbody></table></div>}
        </section>

        <section className="panel raw-model-panel"><button onClick={() => setRawOpen((value) => !value)}><div><span className="eyebrow">Full transparency</span><strong>Raw production fields</strong></div>{rawOpen ? <ChevronUp size={17}/> : <ChevronDown size={17}/>}</button>{rawOpen && <div className="raw-field-grid">{Object.entries(profile.raw_model_fields).filter(([, value]) => value !== null && value !== undefined && value !== '').map(([key, value]) => <div key={key}><span>{key.replaceAll('_', ' ')}</span><strong>{typeof value === 'number' ? metric(value, 3) : String(value)}</strong></div>)}</div>}</section>
      </>}
    </main>
  </div>;
}
