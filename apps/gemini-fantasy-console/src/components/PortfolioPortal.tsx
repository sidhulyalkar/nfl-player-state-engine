import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, Layers3, RefreshCw, ShieldCheck, UsersRound } from 'lucide-react';
import type { PortfolioExposureResponse } from '../../shared/types';
import { api } from '../lib/api';

function pct(value: number | null | undefined, digits = 0) {
  return value == null || !Number.isFinite(value) ? '—' : `${(value * 100).toFixed(digits)}%`;
}

export function PortfolioPortal() {
  const [payload, setPayload] = useState<PortfolioExposureResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState('ALL');

  const refresh = () => {
    setLoading(true);
    api.portfolioExposure().then((result) => {
      setPayload(result);
      setError(null);
    }).catch((reason) => {
      setError(reason instanceof Error ? reason.message : 'Portfolio exposure unavailable.');
    }).finally(() => setLoading(false));
  };

  useEffect(() => {
    refresh();
  }, []);

  const positions = useMemo(() => Array.from(new Set((payload?.players ?? []).map((row) => row.position).filter(Boolean))) as string[], [payload]);
  const players = useMemo(() => (payload?.players ?? []).filter((row) => filter === 'ALL' || row.position === filter), [filter, payload]);
  const summary = payload?.summary;

  return <div className="portal-shell portfolio-portal">
    <header className="portal-header">
      <div><span className="eyebrow">Across every connected fantasy league</span><h1>Portfolio Exposure</h1><p>See repeated player, team and position bets before adding more correlated exposure. Identity resolution stays explicit so cross-platform matches are never guessed.</p></div>
      <div className="portal-actions"><button onClick={refresh} disabled={loading}><RefreshCw size={16} className={loading ? 'spin' : ''}/>Refresh exposure</button></div>
    </header>

    {error && <div className="portal-warning"><AlertTriangle size={16}/><span>{error}</span></div>}

    <div className="portfolio-summary-grid">
      <article><Layers3 size={18}/><span>Resolved leagues</span><strong>{summary ? `${summary.resolved_user_rosters}/${summary.stored_leagues}` : '—'}</strong><small>{summary?.unresolved_user_rosters ?? 0} excluded rather than guessed</small></article>
      <article><UsersRound size={18}/><span>Unique player keys</span><strong>{summary?.unique_player_keys ?? '—'}</strong><small>{summary?.total_roster_slots ?? '—'} roster slots tracked</small></article>
      <article><ShieldCheck size={18}/><span>Canonical identity rows</span><strong>{summary?.canonical_identity_rows ?? '—'}</strong><small>{summary?.platform_scoped_identity_rows ?? '—'} platform-scoped only</small></article>
      <article><AlertTriangle size={18}/><span>Highest player exposure</span><strong>{pct(summary?.maximum_single_player_exposure)}</strong><small>visibility signal, not an automatic sell flag</small></article>
    </div>

    <div className="portfolio-layout">
      <main className="panel portfolio-player-panel">
        <div className="panel-heading"><div><span className="eyebrow">Repeated bets</span><h2>Player exposure across leagues</h2></div><div className="portfolio-filters"><button className={filter === 'ALL' ? 'active' : ''} onClick={() => setFilter('ALL')}>ALL</button>{positions.map((position) => <button key={position} className={filter === position ? 'active' : ''} onClick={() => setFilter(position)}>{position}</button>)}</div></div>
        {!players.length ? <div className="shadow-empty"><AlertTriangle size={16}/><span>No resolved player exposure rows yet.</span></div> : <div className="portfolio-player-list">{players.map((player) => <article key={player.player_key}>
          <div className="portfolio-player-head"><div><span className={`position-tag ${String(player.position ?? '').toLowerCase()}`}>{player.position ?? '—'}</span><div><strong>{player.player_name}</strong><small>{player.nfl_team ?? 'team unknown'} · {player.identity_quality.replaceAll('_', ' ')}</small></div></div><div><strong>{player.league_count} leagues</strong><span>{pct(player.exposure_rate)} exposure</span></div></div>
          <div className="portfolio-exposure-track"><i style={{ width: `${Math.max(0, Math.min(100, (player.exposure_rate ?? 0) * 100))}%` }}/></div>
          <div className="portfolio-league-chips">{player.leagues.map((league) => <span key={league.league_id} className={league.is_starter ? 'starter' : ''}>{league.league_name}{league.is_starter ? ' · starter' : ''}</span>)}</div>
        </article>)}</div>}
      </main>

      <aside className="portfolio-side-stack">
        <section className="panel"><div className="panel-heading"><div><span className="eyebrow">NFL team concentration</span><h2>Correlated team bets</h2></div></div><div className="concentration-list">{(payload?.team_concentration ?? []).slice(0, 12).map((row) => <div key={row.nfl_team}><span>{row.nfl_team}</span><div><i style={{ width: `${Math.min(100, row.slots_per_resolved_league * 25)}%` }}/></div><strong>{row.roster_slots}</strong></div>)}</div></section>
        <section className="panel"><div className="panel-heading"><div><span className="eyebrow">Position concentration</span><h2>Roster shape</h2></div></div><div className="concentration-list">{(payload?.position_concentration ?? []).map((row) => <div key={row.position}><span>{row.position}</span><div><i style={{ width: `${Math.min(100, row.slots_per_resolved_league * 18)}%` }}/></div><strong>{row.roster_slots}</strong></div>)}</div></section>
        <section className="panel portfolio-authority"><ShieldCheck size={19}/><div><strong>Exposure is descriptive</strong><p>{payload?.authority.note ?? 'Portfolio identity and exposure rules are server-owned.'}</p></div></section>
        {!!payload?.unresolved_leagues.length && <section className="panel unresolved-panel"><div className="panel-heading"><div><span className="eyebrow">Identity gap</span><h2>Excluded leagues</h2></div></div>{payload.unresolved_leagues.map((league) => <div key={league.league_id}><strong>{league.league_name}</strong><span>{league.reason.replaceAll('_', ' ')}</span></div>)}</section>}
      </aside>
    </div>
  </div>;
}
