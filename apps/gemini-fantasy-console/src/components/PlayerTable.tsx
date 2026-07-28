import type { PlayerRow } from '../../shared/types';
import { SparkRange } from './SparkRange';

export function PlayerTable({ players, title }: { players: PlayerRow[]; title: string }) {
  return (
    <section className="panel table-panel">
      <div className="panel-heading"><div><span className="eyebrow">Live board</span><h2>{title}</h2></div><span className="count-pill">{players.length} players</span></div>
      <div className="table-scroll">
        <table>
          <thead><tr><th>Player</th><th>Owner</th><th>Projection</th><th>Range</th><th>Availability</th><th>Signal</th></tr></thead>
          <tbody>
            {players.map((player) => (
              <tr key={player.player_id}>
                <td><div className="player-cell"><span className={`position-tag ${player.position.toLowerCase()}`}>{player.position}</span><div><strong>{player.player_name}</strong><small>{player.recent_team ?? 'FA'}</small></div></div></td>
                <td>{player.owner_team_name ?? <span className="free-agent">Free agent</span>}</td>
                <td><strong>{player.fantasy_points_ppr_q50?.toFixed(1) ?? '—'}</strong><small> q50</small></td>
                <td><SparkRange floor={player.fantasy_points_ppr_q10} median={player.fantasy_points_ppr_q50} ceiling={player.fantasy_points_ppr_q90} /></td>
                <td>{Math.round((player.availability_probability ?? 1) * 100)}%</td>
                <td><span className="reason-text">{player.decision_reasons ?? 'projection-led value'}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
