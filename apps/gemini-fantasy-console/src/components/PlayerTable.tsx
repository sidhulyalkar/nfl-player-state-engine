import { Download, Search } from 'lucide-react';
import { useMemo, useState } from 'react';
import type { DataMode, PlayerRow } from '../../shared/types';
import { ModeBadge } from './ModeBadge';
import { SparkRange } from './SparkRange';

type SortKey =
  | 'endpoint_order'
  | 'overall_rank'
  | 'position_rank'
  | 'decision_specific_score'
  | 'fantasy_points_ppr_q50'
  | 'vorp'
  | 'waiver_upgrade'
  | 'faab_recommendation'
  | 'lineup_delta';

interface Props {
  players: PlayerRow[];
  title: string;
  mode: DataMode;
  eyebrow?: string;
  emptyMessage?: string;
  showLineup?: boolean;
  defaultSortKey?: SortKey;
}

const sortLabels: Record<SortKey, string> = {
  endpoint_order: 'Recommended order',
  overall_rank: 'Overall rank',
  position_rank: 'Position rank',
  decision_specific_score: 'Decision score',
  fantasy_points_ppr_q50: 'Median projection',
  vorp: 'VORP',
  waiver_upgrade: 'Waiver upgrade',
  faab_recommendation: 'FAAB recommendation',
  lineup_delta: 'Lineup improvement',
};

function numeric(player: PlayerRow, key: SortKey) {
  if (key === 'endpoint_order') return 0;
  if (key === 'vorp') {
    return player.vorp ?? (
      player.season_points_q50 !== undefined && player.replacement_points !== undefined
        ? player.season_points_q50 - player.replacement_points
        : Number.NEGATIVE_INFINITY
    );
  }
  return player[key] ?? (key.includes('rank') ? Number.POSITIVE_INFINITY : Number.NEGATIVE_INFINITY);
}

function ranked(players: PlayerRow[]) {
  const sorted = [...players].sort((a, b) => (b.decision_specific_score ?? -Infinity) - (a.decision_specific_score ?? -Infinity));
  const byPosition = new Map<string, number>();
  const fallbackRanks = new Map<string, { overall: number; position: number }>();
  sorted.forEach((player, index) => {
    const positionRank = (byPosition.get(player.position) ?? 0) + 1;
    byPosition.set(player.position, positionRank);
    fallbackRanks.set(player.player_id, { overall: index + 1, position: positionRank });
  });
  return players.map((player) => {
    const fallback = fallbackRanks.get(player.player_id);
    return {
      ...player,
      overall_rank: player.overall_rank ?? fallback?.overall,
      position_rank: player.position_rank ?? fallback?.position,
    };
  });
}

function csvCell(value: unknown) {
  return `"${String(value ?? '').replaceAll('"', '""')}"`;
}

export function PlayerTable({
  players,
  title,
  mode,
  eyebrow = 'Decision board',
  emptyMessage = 'No eligible players were returned for this view.',
  showLineup = false,
  defaultSortKey = 'overall_rank',
}: Props) {
  const [search, setSearch] = useState('');
  const [position, setPosition] = useState('ALL');
  const [sortKey, setSortKey] = useState<SortKey>(defaultSortKey);
  const normalized = useMemo(() => ranked(players), [players]);
  const positions = useMemo(() => ['ALL', ...Array.from(new Set(normalized.map((player) => player.position))).sort()], [normalized]);
  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase();
    const filtered = normalized.filter((player) => (
      (position === 'ALL' || player.position === position)
      && (!needle || `${player.player_name} ${player.recent_team ?? ''} ${player.owner_team_name ?? ''}`.toLowerCase().includes(needle))
    ));
    if (sortKey === 'endpoint_order') return filtered;
    return filtered.sort((a, b) => {
      const left = numeric(a, sortKey);
      const right = numeric(b, sortKey);
      return sortKey.includes('rank') ? left - right : right - left;
    });
  }, [normalized, position, search, sortKey]);

  function exportBoard() {
    const header = ['overall_rank', 'position_rank', 'player_name', 'position', 'team', 'owner', 'decision_score', 'q10', 'q50', 'q90', 'replacement_points', 'vorp', 'reasons'];
    const lines = visible.map((player) => [
      player.overall_rank,
      player.position_rank,
      player.player_name,
      player.position,
      player.recent_team,
      player.owner_team_name ?? 'Free agent',
      player.decision_specific_score,
      player.fantasy_points_ppr_q10,
      player.fantasy_points_ppr_q50,
      player.fantasy_points_ppr_q90,
      player.replacement_points ?? player.roster_replacement_value,
      numeric(player, 'vorp') === Number.NEGATIVE_INFINITY ? '' : numeric(player, 'vorp'),
      player.decision_reasons,
    ].map(csvCell).join(','));
    const blob = new Blob([[header.join(','), ...lines].join('\n')], { type: 'text/csv;charset=utf-8' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `${title.toLowerCase().replaceAll(/[^a-z0-9]+/g, '-')}.csv`;
    link.click();
    URL.revokeObjectURL(link.href);
  }

  return (
    <section className="panel table-panel">
      <div className="panel-heading board-heading">
        <div><span className="eyebrow">{eyebrow}</span><h2>{title}</h2></div>
        <div className="panel-meta"><ModeBadge mode={mode}/><span className="count-pill">{visible.length} players</span></div>
      </div>
      <div className="board-controls">
        <label className="search-control"><span className="sr-only">Search players</span><Search size={15}/><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search player, team, owner…"/></label>
        <label><span className="sr-only">Filter position</span><select value={position} onChange={(event) => setPosition(event.target.value)}>{positions.map((item) => <option value={item} key={item}>{item === 'ALL' ? 'All positions' : item}</option>)}</select></label>
        <label><span className="sr-only">Sort player board</span><select value={sortKey} onChange={(event) => setSortKey(event.target.value as SortKey)}>{Object.entries(sortLabels).map(([key, label]) => <option value={key} key={key}>{label}</option>)}</select></label>
        <button type="button" className="secondary-button" onClick={exportBoard} disabled={!visible.length}><Download size={15}/> Export CSV</button>
      </div>
      <div className="table-scroll">
        <table>
          <thead><tr><th>Ranks</th><th>Player</th>{showLineup && <th>Slot</th>}<th>Owner</th><th>Decision</th><th>Projection</th><th>Range</th><th>Replacement</th><th>Signal</th></tr></thead>
          <tbody>
            {!visible.length && <tr><td colSpan={showLineup ? 9 : 8} className="empty-cell">{emptyMessage}</td></tr>}
            {visible.map((player) => {
              const vorp = numeric(player, 'vorp');
              return (
                <tr key={`${player.player_id}-${player.lineup_slot ?? player.slot ?? ''}`}>
                  <td><strong>#{player.overall_rank}</strong><small className="rank-sub">{player.position}{player.position_rank}</small></td>
                  <td><div className="player-cell"><span className={`position-tag ${player.position.toLowerCase()}`}>{player.position}</span><div><strong>{player.player_name}</strong><small>{player.recent_team ?? 'FA'}</small></div></div></td>
                  {showLineup && <td><span className="slot-pill">{player.assigned_slot ?? player.lineup_slot ?? player.slot ?? 'START'}</span></td>}
                  <td>{player.owner_team_name ?? <span className="free-agent">Free agent</span>}</td>
                  <td><strong>{player.decision_specific_score?.toFixed(1) ?? '—'}</strong><small className="rank-sub">score</small></td>
                  <td><strong>{player.fantasy_points_ppr_q50?.toFixed(1) ?? '—'}</strong><small> q50</small></td>
                  <td><SparkRange floor={player.fantasy_points_ppr_q10} median={player.fantasy_points_ppr_q50} ceiling={player.fantasy_points_ppr_q90} /></td>
                  <td><strong>{vorp === Number.NEGATIVE_INFINITY ? '—' : `${vorp >= 0 ? '+' : ''}${vorp.toFixed(1)}`}</strong><small className="rank-sub">VORP</small></td>
                  <td><span className="reason-text">{player.decision_reasons ?? 'No reason codes returned'}</span></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
