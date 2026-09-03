import { useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  BarChart3,
  CheckCircle2,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Target,
  Trophy,
} from 'lucide-react';
import { api } from '../lib/api';
import type {
  ShowcasePlayerRow,
  ShowcaseScopeMetrics,
  ShowcaseSeasonResponse,
  ShowcaseWeekResponse,
  ShowcaseWinner,
} from '../lib/showcaseTypes';
import '../model-showcase.css';

const POSITIONS = ['ALL', 'QB', 'RB', 'WR', 'TE'];

function number(value: number | null | undefined, digits = 2) {
  return value == null || Number.isNaN(value) ? '—' : value.toFixed(digits);
}

function pct(value: number | null | undefined) {
  return value == null || Number.isNaN(value) ? '—' : `${Math.round(value * 100)}%`;
}

function winnerCopy(winner: ShowcaseWinner) {
  if (winner === 'model') return 'Fourth Down Lab';
  if (winner === 'expert') return 'Expert consensus';
  if (winner === 'tie') return 'Dead heat';
  return 'Rank-only audit';
}

function winnerTone(winner: ShowcaseWinner) {
  return `showcase-winner showcase-winner-${winner}`;
}

function MetricTile({ label, model, expert, suffix = '' }: {
  label: string;
  model?: number | null;
  expert?: number | null;
  suffix?: string;
}) {
  const modelWins = model != null && expert != null && model < expert;
  const expertWins = model != null && expert != null && expert < model;
  return <div className="showcase-metric-tile">
    <span>{label}</span>
    <div className="showcase-metric-versus">
      <div className={modelWins ? 'metric-leader' : ''}><small>MODEL</small><strong>{number(model)}{suffix}</strong></div>
      <b>vs</b>
      <div className={expertWins ? 'metric-leader' : ''}><small>EXPERTS</small><strong>{number(expert)}{suffix}</strong></div>
    </div>
  </div>;
}

function SeasonTrend({ season }: { season: ShowcaseSeasonResponse }) {
  const max = Math.max(
    1,
    ...season.weeks.flatMap((item) => [item.model_rank_mae ?? 0, item.expert_rank_mae ?? 0]),
  );
  return <section className="showcase-card trend-card">
    <div className="showcase-card-heading">
      <div><span className="eyebrow">Season tape</span><h2>Weekly rank error</h2></div>
      <div className="trend-legend"><span className="model-dot"/>Model <span className="expert-dot"/>Experts</div>
    </div>
    <div className="trend-bars" role="img" aria-label="Weekly model and expert positional rank error">
      {season.weeks.map((item) => <div className="trend-week" key={item.week}>
        <div className="trend-columns">
          <i className="trend-model" style={{ height: `${Math.max(4, ((item.model_rank_mae ?? 0) / max) * 100)}%` }}/>
          <i className="trend-expert" style={{ height: `${Math.max(4, ((item.expert_rank_mae ?? 0) / max) * 100)}%` }}/>
        </div>
        <span>W{item.week}</span>
      </div>)}
    </div>
  </section>;
}

function Scatter({ players }: { players: ShowcasePlayerRow[] }) {
  const visible = players.filter((row) => Number.isFinite(row.model_points) && Number.isFinite(row.actual_points)).slice(0, 60);
  const max = Math.max(1, ...visible.flatMap((row) => [row.model_points, row.actual_points])) * 1.08;
  return <section className="showcase-card scatter-card">
    <div className="showcase-card-heading"><div><span className="eyebrow">Projection geometry</span><h2>Model vs reality</h2></div><small>Closer to the diagonal is better.</small></div>
    {visible.length ? <svg viewBox="0 0 100 100" className="showcase-scatter" aria-label="Model projected points versus actual fantasy points">
      <line x1="5" y1="95" x2="95" y2="5" className="scatter-reference"/>
      {visible.map((row) => {
        const x = 5 + (row.model_points / max) * 90;
        const y = 95 - (row.actual_points / max) * 90;
        return <circle key={row.player_id} cx={x} cy={y} r="1.8" className={`scatter-point scatter-${row.position.toLowerCase()}`}><title>{row.player_name}: model {number(row.model_points, 1)}, actual {number(row.actual_points, 1)}</title></circle>;
      })}
    </svg> : <div className="showcase-empty-compact">No comparable point rows for this filter.</div>}
  </section>;
}

function PositionBattle({ position, metrics, winner }: {
  position: string;
  metrics: ShowcaseScopeMetrics;
  winner: ShowcaseWinner;
}) {
  return <div className={`position-battle battle-${winner}`}>
    <div><strong>{position}</strong><span>{winnerCopy(winner)}</span></div>
    <dl>
      <div><dt>Rank error</dt><dd>{number(metrics.model_rank_mae)} <small>vs {number(metrics.expert_rank_mae)}</small></dd></div>
      <div><dt>Top {metrics.top_n ?? 'N'}</dt><dd>{pct(metrics.model_top_n_hit_rate)} <small>vs {pct(metrics.expert_top_n_hit_rate)}</small></dd></div>
    </dl>
  </div>;
}

function CallCard({ row, kind }: { row: ShowcasePlayerRow; kind: 'hit' | 'miss' }) {
  return <article className={`call-card call-card-${kind}`}>
    <div className="call-rank"><span>{row.position}</span><strong>{row.actual_rank ? `#${number(row.actual_rank, 0)}` : '—'}</strong></div>
    <div><h3>{row.player_name}</h3><p>{kind === 'hit' ? `We beat consensus by ${number(row.rank_edge_vs_expert, 1)} rank spots of error.` : `Our rank missed reality by ${number(row.model_rank_error, 1)} spots.`}</p></div>
    <dl><div><dt>Model</dt><dd>#{number(row.model_rank, 0)}</dd></div><div><dt>Experts</dt><dd>#{number(row.expert_rank, 0)}</dd></div><div><dt>Actual</dt><dd>#{number(row.actual_rank, 0)}</dd></div></dl>
  </article>;
}

export function ModelShowcasePortal() {
  const [season, setSeason] = useState<number>();
  const [week, setWeek] = useState<number>();
  const [seasonData, setSeasonData] = useState<ShowcaseSeasonResponse>();
  const [weekData, setWeekData] = useState<ShowcaseWeekResponse>();
  const [availableSeasons, setAvailableSeasons] = useState<Array<{ season: number; weeks: number[]; latest_week: number }>>([]);
  const [position, setPosition] = useState('ALL');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();

  useEffect(() => {
    let active = true;
    api.modelShowcaseIndex().then((index) => {
      if (!active) return;
      setAvailableSeasons(index.seasons);
      const first = index.seasons[0];
      if (first) {
        setSeason(first.season);
        setWeek(first.latest_week);
      }
      setLoading(false);
    }).catch((reason: unknown) => {
      if (!active) return;
      setError(reason instanceof Error ? reason.message : String(reason));
      setLoading(false);
    });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (season == null) return;
    let active = true;
    api.modelShowcaseSeason(season).then((payload) => {
      if (active) setSeasonData(payload);
    }).catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason.message : String(reason));
    });
    return () => { active = false; };
  }, [season]);

  useEffect(() => {
    if (season == null || week == null) return;
    let active = true;
    setLoading(true);
    api.modelShowcaseWeek(season, week).then((payload) => {
      if (!active) return;
      setWeekData(payload);
      setError(undefined);
      setLoading(false);
    }).catch((reason: unknown) => {
      if (!active) return;
      setError(reason instanceof Error ? reason.message : String(reason));
      setLoading(false);
    });
    return () => { active = false; };
  }, [season, week]);

  const selectedSeason = availableSeasons.find((item) => item.season === season);
  const players = useMemo(() => {
    const all = weekData?.players ?? [];
    return position === 'ALL' ? all : all.filter((row) => row.position === position);
  }, [position, weekData]);
  const rankedPlayers = useMemo(
    () => [...players].sort((a, b) => b.rank_edge_vs_expert - a.rank_edge_vs_expert),
    [players],
  );

  if (!loading && !availableSeasons.length) {
    return <div className="portal-shell showcase-portal"><div className="showcase-empty"><BarChart3/><h1>Performance Scoreboard</h1><p>No frozen weekly comparisons exist yet. Build the first artifact after a completed week; the UI will stay empty rather than inventing a demo victory.</p><code>python scripts/build_weekly_showcase.py --help</code></div></div>;
  }

  return <div className="portal-shell showcase-portal">
    <header className="portal-header showcase-header">
      <div><span className="eyebrow">Frozen weekly evidence · model vs experts vs reality</span><h1>Performance Scoreboard</h1><p>A season-long receipts drawer. Every result comes from timestamped snapshots and completed outcomes; this workspace can explain the production model, but it cannot promote or alter it.</p></div>
      <div className="showcase-authority"><ShieldCheck size={17}/><span><strong>Evaluation only</strong><small>No decision authority</small></span></div>
    </header>

    <div className="showcase-toolbar">
      <label>Season<select value={season ?? ''} onChange={(event) => {
        const next = Number(event.target.value);
        setSeason(next);
        const match = availableSeasons.find((item) => item.season === next);
        setWeek(match?.latest_week);
      }}>{availableSeasons.map((item) => <option key={item.season} value={item.season}>{item.season}</option>)}</select></label>
      <div className="week-strip" aria-label="Available weeks">{selectedSeason?.weeks.map((item) => <button key={item} className={week === item ? 'active' : ''} onClick={() => setWeek(item)}>W{item}</button>)}</div>
      <button className="showcase-refresh" onClick={() => {
        if (season != null && week != null) {
          setLoading(true);
          api.modelShowcaseWeek(season, week).then((payload) => { setWeekData(payload); setLoading(false); }).catch((reason: unknown) => { setError(reason instanceof Error ? reason.message : String(reason)); setLoading(false); });
        }
      }}><RefreshCw size={15}/>Refresh</button>
    </div>

    {error && <div className="showcase-error"><AlertTriangle size={17}/><span>{error}</span></div>}
    {loading && !weekData && <div className="showcase-loading"><RefreshCw className="spin"/>Loading frozen scoreboard…</div>}

    {weekData && <>
      <section className="showcase-hero">
        <div className="showcase-hero-copy"><span className={winnerTone(weekData.metrics.winner)}><Trophy size={16}/>{winnerCopy(weekData.metrics.winner)}</span><h2>Week {weekData.manifest.week}</h2><p>{weekData.narrative.headline}</p><div className="showcase-provenance"><span>Model: {weekData.manifest.snapshots.model?.source}</span><span>Experts: {weekData.manifest.snapshots.expert?.source}</span><span>{weekData.manifest.rows} matched players</span></div></div>
        <div className="showcase-scorebox"><span>Season record</span><strong>{seasonData?.record.model_wins ?? 0}<small>–</small>{seasonData?.record.expert_wins ?? 0}</strong><p>model wins · expert wins</p></div>
      </section>

      <section className="showcase-metric-grid">
        <MetricTile label="Positional rank MAE" model={weekData.metrics.overall.model_rank_mae} expert={weekData.metrics.overall.expert_rank_mae}/>
        <MetricTile label="Fantasy-point MAE" model={weekData.metrics.overall.model_mae} expert={weekData.metrics.overall.expert_mae}/>
        <div className="showcase-metric-tile"><span>80% interval coverage</span><div className="solo-metric"><strong>{pct(weekData.metrics.overall.model_interval_coverage_80)}</strong><small>{weekData.metrics.overall.model_interval_coverage_80 == null ? 'No qualified q10/q90 in this artifact' : `target 80% · width ${number(weekData.metrics.overall.model_interval_mean_width, 1)}`}</small></div></div>
      </section>

      <section className="showcase-card battle-card">
        <div className="showcase-card-heading"><div><span className="eyebrow">Round by round</span><h2>Position battles</h2></div><Target size={19}/></div>
        <div className="position-battles">{Object.entries(weekData.metrics.positions).map(([key, metrics]) => <PositionBattle key={key} position={key} metrics={metrics} winner={weekData.metrics.position_battles[key]?.winner ?? 'unavailable'}/>)}</div>
      </section>

      {seasonData && <SeasonTrend season={seasonData}/>} 

      <div className="showcase-two-column">
        <Scatter players={players}/>
        <section className="showcase-card calls-panel">
          <div className="showcase-card-heading"><div><span className="eyebrow">Receipts</span><h2>Best calls</h2></div><Sparkles size={18}/></div>
          <div className="call-stack">{weekData.narrative.best_calls.slice(0, 3).map((row) => <CallCard key={row.player_id} row={row} kind="hit"/>)}</div>
        </section>
      </div>

      <section className="showcase-card player-table-card">
        <div className="showcase-card-heading"><div><span className="eyebrow">Player tape</span><h2>Where the edge came from</h2></div><div className="position-filter">{POSITIONS.map((item) => <button key={item} className={position === item ? 'active' : ''} onClick={() => setPosition(item)}>{item}</button>)}</div></div>
        <div className="showcase-table-wrap"><table className="showcase-table"><thead><tr><th>Player</th><th>Model</th><th>Experts</th><th>Actual</th><th>Rank edge</th><th>Points</th><th>Actual pts</th></tr></thead><tbody>{rankedPlayers.slice(0, 60).map((row) => <tr key={row.player_id}><td><strong>{row.player_name}</strong><small>{row.position} · {row.nfl_team || '—'}</small></td><td>#{number(row.model_rank, 0)}</td><td>#{number(row.expert_rank, 0)}</td><td>#{number(row.actual_rank, 0)}</td><td className={row.rank_edge_vs_expert > 0 ? 'edge-positive' : row.rank_edge_vs_expert < 0 ? 'edge-negative' : ''}>{row.rank_edge_vs_expert > 0 ? '+' : ''}{number(row.rank_edge_vs_expert, 1)}</td><td>{number(row.model_points, 1)}</td><td>{number(row.actual_points, 1)}</td></tr>)}</tbody></table></div>
      </section>

      <section className="showcase-card reality-check-card">
        <div className="showcase-card-heading"><div><span className="eyebrow">Reality check</span><h2>Biggest misses</h2></div><AlertTriangle size={18}/></div>
        <div className="miss-grid">{weekData.narrative.biggest_misses.slice(0, 4).map((row) => <CallCard key={row.player_id} row={row} kind="miss"/>)}</div>
      </section>

      <footer className="showcase-footer"><CheckCircle2 size={16}/><span>Artifact <code>{weekData.manifest.artifact_id.slice(0, 12)}</code> · scoring {weekData.manifest.scoring} · generated {new Date(weekData.manifest.generated_at_utc).toLocaleString()}</span></footer>
    </>}
  </div>;
}
