import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';
import type { DataMode, LeagueSummary, PlayerRow } from '../../shared/types';
import { api } from '../lib/api';
import { demoPlayers } from '../lib/demo';
import { PlayerIntelligenceView } from './PlayerIntelligenceView';

function modeFor(players: PlayerRow[], demo: boolean): DataMode {
  if (demo) return 'synthetic';
  const raw = String(players[0]?.data_mode ?? '').toUpperCase();
  if (raw.includes('LIVE')) return 'live';
  if (raw.includes('HISTORICAL') || raw.includes('RESEARCH')) return 'historical';
  return 'unverified';
}

export function IntelligencePortal() {
  const [leagues, setLeagues] = useState<LeagueSummary[]>([]);
  const [leagueId, setLeagueId] = useState('demo-league');
  const [players, setPlayers] = useState<PlayerRow[]>(demoPlayers);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    api.leagues().then((items) => {
      if (!active) return;
      setLeagues(items);
      if (items.length) setLeagueId((current) => current === 'demo-league' ? items[0].league_id : current);
    }).catch(() => {
      if (active) setLeagues([]);
    });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (leagueId === 'demo-league') {
      setPlayers(demoPlayers);
      setError(null);
      return;
    }
    let active = true;
    setLoading(true);
    api.players(leagueId, 'trade').then((rows) => {
      if (!active) return;
      setPlayers(rows);
      setError(null);
    }).catch((reason) => {
      if (!active) return;
      setPlayers([]);
      setError(reason instanceof Error ? reason.message : 'Player board unavailable.');
    }).finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [leagueId]);

  const mode = useMemo(() => modeFor(players, leagueId === 'demo-league'), [leagueId, players]);

  return <div className="portal-shell">
    <header className="portal-header">
      <div><span className="eyebrow">All model data for one player</span><h1>Player Intelligence</h1><p>Search the complete league board, inspect every decision-specific valuation, and compare current projections with frozen historical replay.</p></div>
      <div className="portal-actions"><label><span>League</span><select value={leagueId} onChange={(event) => setLeagueId(event.target.value)}><option value="demo-league">Visual demo</option>{leagues.map((league) => <option key={league.league_id} value={league.league_id}>{league.name}</option>)}</select></label>{loading && <RefreshCw size={17} className="spin"/>}</div>
    </header>
    {error && <div className="portal-warning"><AlertTriangle size={16}/><span>{error}</span></div>}
    <PlayerIntelligenceView leagueId={leagueId} players={players} mode={mode}/>
  </div>;
}
