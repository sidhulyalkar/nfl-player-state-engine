import type { ChangeEvent, CSSProperties } from 'react';
import { useEffect, useMemo, useState } from 'react';
import {
  Activity, AlertTriangle, BarChart3, Bot, CheckCircle2, Database, FlaskConical, Gauge,
  LayoutDashboard, Repeat2, Search, Shield, Trophy, Users,
} from 'lucide-react';
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type {
  DataMode, DecisionType, LeagueNeedsResponse, LeagueSummary, NFLStateSnapshot, NavPage,
  PlayerRow, PowerRanking, ResearchPrediction, ResearchSummary, TeamContextResponse, TradeSide,
  TradeSuggestion,
} from '../shared/types';
import { Copilot } from './components/Copilot';
import { ModeBadge } from './components/ModeBadge';
import { PlayerTable } from './components/PlayerTable';
import { TrustStrip } from './components/TrustStrip';
import { api } from './lib/api';
import { demoLineup, demoNFL, demoPlayers, demoPower, demoTrades, demoWaivers } from './lib/demo';
import './styles.css';
import './enhancements.css';

const nav: Array<[NavPage, string, typeof LayoutDashboard]> = [
  ['overview', 'Command Center', LayoutDashboard], ['league', 'League Picture', Users],
  ['players', 'Player Lab', Search], ['trade', 'Trade Lab', Repeat2],
  ['waivers', 'Opportunity Wire', Activity], ['lineup', 'Lineup Lab', Shield],
  ['nfl', 'NFL State', Trophy], ['model', 'Model Lab', FlaskConical],
];

const decisions: Array<[DecisionType, string]> = [
  ['start_sit', 'Weekly / start-sit'], ['waiver', 'Waiver'], ['trade', 'Trade'],
  ['draft', 'Draft'], ['stash', 'Stash'], ['dynasty', 'Dynasty'],
];

function normalizeDataMode(raw: string | undefined, fallback: DataMode): DataMode {
  const value = raw?.toUpperCase() ?? '';
  if (value.includes('SYNTHETIC') || value.includes('DEMO')) return 'synthetic';
  if (value.includes('HISTORICAL') || value.includes('RESEARCH')) return 'historical';
  if (value.includes('LIVE')) return 'live';
  if (value.includes('UNVERIFIED') || value.includes('UNKNOWN')) return 'unverified';
  return fallback;
}

function value(record: Record<string, unknown> | undefined, names: string[]) {
  if (!record) return undefined;
  for (const name of names) {
    const candidate = Number(record[name]);
    if (Number.isFinite(candidate)) return candidate;
  }
  return undefined;
}

function text(record: Record<string, unknown>, names: string[]) {
  for (const name of names) {
    const candidate = record[name];
    if (candidate !== undefined && candidate !== null && candidate !== '') return String(candidate);
  }
  return undefined;
}

function signed(number: number | undefined) {
  return number === undefined ? '—' : `${number > 0 ? '+' : ''}${number.toFixed(1)}`;
}

function formatMetric(number: number | undefined, digits = 3) {
  return number === undefined ? '—' : number.toFixed(digits);
}

function statusMessage(error: unknown) {
  return error instanceof Error ? error.message : 'Request unavailable';
}

export default function App() {
  const [page, setPage] = useState<NavPage>('overview');
  const [leagues, setLeagues] = useState<LeagueSummary[]>([]);
  const [leagueId, setLeagueId] = useState('demo-league');
  const [rosterId, setRosterId] = useState('1');
  const [decision, setDecision] = useState<DecisionType>('trade');
  const [players, setPlayers] = useState<PlayerRow[]>(demoPlayers);
  const [waivers, setWaivers] = useState<PlayerRow[]>(demoWaivers);
  const [lineup, setLineup] = useState<PlayerRow[]>(demoLineup);
  const [power, setPower] = useState<PowerRanking[]>(demoPower);
  const [trades, setTrades] = useState<TradeSuggestion[]>(demoTrades);
  const [nflState, setNflState] = useState<NFLStateSnapshot>(demoNFL);
  const [needs, setNeeds] = useState<LeagueNeedsResponse | null>(null);
  const [research, setResearch] = useState<ResearchSummary | null>(null);
  const [teamContext, setTeamContext] = useState<TeamContextResponse | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const isDemo = leagueId === 'demo-league';
  const league = leagues.find((item) => item.league_id === leagueId);
  const mode = normalizeDataMode(
    needs?.data_mode ?? players[0]?.data_mode,
    isDemo ? 'synthetic' : 'unverified',
  );

  function recordError(key: string, error: unknown) {
    setErrors((current) => ({ ...current, [key]: statusMessage(error) }));
  }

  function clearError(key: string) {
    setErrors((current) => {
      if (!(key in current)) return current;
      const next = { ...current };
      delete next[key];
      return next;
    });
  }

  useEffect(() => {
    let active = true;
    api.leagues().then((items) => {
      if (!active) return;
      setLeagues(items);
      clearError('leagues');
    }).catch((error) => active && recordError('leagues', error));
    api.researchSummary().then((payload) => {
      if (!active) return;
      setResearch(payload);
      clearError('research');
    }).catch((error) => active && recordError('research', error));
    return () => { active = false; };
  }, []);

  useEffect(() => {
    let active = true;
    if (page === 'nfl' && !teamContext) api.teamContext().then((payload) => {
      if (!active) return;
      const result = payload as unknown as TeamContextResponse | TeamContextResponse['teams'];
      setTeamContext(Array.isArray(result) ? { teams: result } : result);
      clearError('teamContext');
    }).catch((error) => active && recordError('teamContext', error));
    return () => { active = false; };
  }, [page]);

  useEffect(() => {
    if (isDemo) {
      setPlayers(demoPlayers);
      clearError('players');
      return;
    }
    let active = true;
    setPlayers([]);
    clearError('players');
    api.players(leagueId, decision).then((items) => {
      if (active) setPlayers(items);
    }).catch((error) => active && recordError('players', error));
    return () => { active = false; };
  }, [decision, isDemo, leagueId]);

  useEffect(() => {
    if (isDemo) {
      setPower(demoPower); setTrades(demoTrades); setWaivers(demoWaivers);
      setLineup(demoLineup); setNflState(demoNFL); setNeeds(null);
      ['power', 'trades', 'waivers', 'lineup', 'needs', 'nfl'].forEach(clearError);
      return;
    }
    let active = true;
    setPower([]); setTrades([]); setWaivers([]); setLineup([]); setNeeds(null);
    setNflState({ season: league?.season ?? new Date().getFullYear(), teams: [] });
    ['power', 'trades', 'waivers', 'lineup', 'needs', 'nfl'].forEach(clearError);
    api.powerRankings(leagueId).then((items) => {
      if (!active) return;
      setPower(items);
      if (items.length && !items.some((item) => item.roster_id === rosterId)) setRosterId(items[0].roster_id);
    }).catch((error) => active && recordError('power', error));
    api.tradeSuggestions(leagueId, rosterId).then((items) => active && setTrades(items)).catch((error) => active && recordError('trades', error));
    api.waivers(leagueId, rosterId).then((items) => active && setWaivers(items)).catch((error) => active && recordError('waivers', error));
    api.lineup(leagueId, rosterId).then((items) => active && setLineup(items)).catch((error) => active && recordError('lineup', error));
    api.needs(leagueId).then((payload) => active && setNeeds(payload)).catch((error) => active && recordError('needs', error));
    api.nflState(league?.season ?? new Date().getFullYear()).then((payload) => active && setNflState(payload)).catch((error) => active && recordError('nfl', error));
    return () => { active = false; };
  }, [isDemo, league?.season, leagueId, rosterId]);

  const selectedPower = power.find((team) => team.roster_id === rosterId) ?? power[0];
  const missingInputs = [
    ...(isDemo ? ['live league snapshot', 'authoritative projection provenance'] : needs?.missing_inputs ?? []),
    ...(!isDemo && mode === 'unverified' ? ['verified projection provenance'] : []),
    ...(!isDemo ? Object.keys(errors).filter((key) => ['players', 'power', 'needs'].includes(key)).map((key) => `${key} unavailable`) : []),
  ];
  const firstPlayer = players[0];
  const provenance = page === 'model'
    ? {
        mode: 'historical' as DataMode,
        label: 'Historical research artifacts',
        artifactModifiedAt: research?.artifact_file_modified_at,
        missingInputs: research?.missing_inputs ?? (errors.research ? ['research summary unavailable'] : []),
      }
    : {
        mode,
        label: isDemo
          ? 'Bundled deterministic fixture'
          : mode === 'unverified'
            ? 'Connected league; projection provenance unverified'
            : 'Connected league response',
        modelVersion: needs?.model_version ?? firstPlayer?.model_version,
        predictionTimestamp: firstPlayer?.prediction_timestamp,
        artifactModifiedAt: needs?.projection_artifact_file_modified_at ?? firstPlayer?.projection_artifact_file_modified_at,
        featureCutoff: firstPlayer?.source_cutoff ?? firstPlayer?.feature_cutoff,
        sourceCoverage: needs?.identity_coverage?.coverage_rate,
        unresolvedPlayerIds: needs?.identity_coverage?.unresolved_players,
        missingInputs,
      };

  const heroNarrative = useMemo(() => {
    if (!selectedPower) return 'Team assessment unavailable because no league power-ranking response was returned.';
    const rank = [...power].sort((a, b) => b.power_score - a.power_score).findIndex((team) => team.roster_id === selectedPower.roster_id) + 1;
    const risk = selectedPower.risk_score >= 65 ? 'high' : selectedPower.risk_score >= 45 ? 'moderate' : 'lower';
    return `Ranks ${rank || '—'} of ${power.length} by league power score, with a ${selectedPower.floor_value.toFixed(0)}–${selectedPower.ceiling_value.toFixed(0)} roster range and ${risk} modeled risk.`;
  }, [power, selectedPower]);

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand"><div className="brand-mark">4D</div><div><strong>Fourth Down Lab</strong><small>Player State Engine</small></div></div>
        <nav aria-label="Primary navigation">{nav.map(([key, label, Icon]) => <button key={key} className={page === key ? 'active' : ''} onClick={() => setPage(key)}><Icon size={18}/>{label}</button>)}</nav>
        <div className="sidebar-foot"><span className={`status-dot ${isDemo ? 'demo' : ''}`}/><div><strong>{isDemo ? 'Synthetic demo active' : 'Product API connected'}</strong><small>Model truth stays server-side</small></div></div>
      </aside>
      <main>
        <header className="topbar">
          <div><span className="eyebrow">League intelligence operating system</span><h1>{nav.find(([key]) => key === page)?.[1]}</h1></div>
          <div className="top-actions">
            <select aria-label="League" value={leagueId} onChange={(event: ChangeEvent<HTMLSelectElement>) => setLeagueId(event.target.value)}>
              <option value="demo-league">Demo League</option>{leagues.filter((item) => item.league_id !== 'demo-league').map((item) => <option key={item.league_id} value={item.league_id}>{item.name}</option>)}
            </select>
            <select aria-label="Roster" value={rosterId} onChange={(event: ChangeEvent<HTMLSelectElement>) => setRosterId(event.target.value)}>{power.map((team) => <option key={team.roster_id} value={team.roster_id}>{team.team_name}</option>)}</select>
            <Copilot leagueId={isDemo ? undefined : leagueId} rosterId={isDemo ? undefined : rosterId}/>
          </div>
        </header>
        <TrustStrip provenance={provenance}/>

        {page === 'overview' && <Overview selectedPower={selectedPower} heroNarrative={heroNarrative} power={power} waivers={waivers} mode={mode}/>}
        {page === 'league' && <LeagueView power={power} needs={needs} players={players} mode={mode} error={errors.needs}/>}
        {page === 'players' && <PlayerView players={players} mode={mode} decision={decision} setDecision={setDecision} error={errors.players}/>}
        {page === 'trade' && <TradeView trades={trades} power={power} mode={mode} error={errors.trades}/>}
        {page === 'waivers' && <WaiverView players={waivers} mode={mode} error={errors.waivers}/>}
        {page === 'lineup' && <LineupView players={lineup} mode={mode} error={errors.lineup}/>}
        {page === 'nfl' && <NFLView nflState={nflState} context={teamContext} stateError={errors.nfl} contextError={errors.teamContext}/>}
        {page === 'model' && <ModelView research={research} error={errors.research}/>}
      </main>
    </div>
  );
}

function Overview({ selectedPower, heroNarrative, power, waivers, mode }: {
  selectedPower?: PowerRanking; heroNarrative: string; power: PowerRanking[]; waivers: PlayerRow[]; mode: DataMode;
}) {
  return <div className="page-grid">
    <section className="hero-card">
      <div><div className="badge-line"><span className="eyebrow">Team state from league response</span><ModeBadge mode={mode}/></div><h2>{selectedPower?.team_name ?? 'Team unavailable'}</h2><p>{heroNarrative}</p></div>
      <div className="hero-score"><span>{selectedPower?.power_score.toFixed(0) ?? '—'}</span><small>power</small></div>
    </section>
    <div className="metric-grid">
      <Metric icon={Gauge} label="Roster value" value={selectedPower?.roster_value.toFixed(0) ?? '—'} note="league adjusted"/>
      <Metric icon={Shield} label="Floor" value={selectedPower?.floor_value.toFixed(0) ?? '—'} note="roster range"/>
      <Metric icon={BarChart3} label="Ceiling" value={selectedPower?.ceiling_value.toFixed(0) ?? '—'} note="roster range"/>
      <Metric icon={Activity} label="Risk" value={selectedPower ? `${selectedPower.risk_score.toFixed(0)}%` : '—'} note="response score"/>
    </div>
    <UnavailablePanel title="Team trajectory unavailable" detail="The Product API does not yet return timestamped team-level projection history. A fabricated week-by-week curve is intentionally not shown."/>
    <section className="panel rankings"><div className="panel-heading"><div><span className="eyebrow">Complete league picture</span><h2>Power rankings</h2></div><ModeBadge mode={mode}/></div>{power.map((team, index) => <div className="ranking-row" key={team.roster_id}><span className="rank-number">{index + 1}</span><div><strong>{team.team_name}</strong><small>{team.record}</small></div><div className="rank-bar"><span style={{ width: `${Math.max(0, Math.min(100, team.power_score))}%` }}/></div><strong>{team.power_score.toFixed(0)}</strong></div>)}</section>
    <PlayerTable players={waivers.slice(0, 12)} title="Highest-leverage free agents" eyebrow="Roster-relative waiver endpoint" mode={mode} defaultSortKey="endpoint_order"/>
  </div>;
}

function LeagueView({ power, needs, players, mode, error }: {
  power: PowerRanking[]; needs: LeagueNeedsResponse | null; players: PlayerRow[]; mode: DataMode; error?: string;
}) {
  const chart = power.map((team) => ({ ...team, range: Math.max(0, team.ceiling_value - team.floor_value) }));
  return <div className="page-grid">
    <section className="panel chart-panel wide"><div className="panel-heading"><div><span className="eyebrow">Roster distribution by manager</span><h2>League strength</h2></div><ModeBadge mode={mode}/></div><ResponsiveContainer width="100%" height={340}><BarChart data={chart}><CartesianGrid strokeDasharray="3 3" stroke="#1d3042"/><XAxis dataKey="team_name" stroke="#7790a5"/><YAxis stroke="#7790a5"/><Tooltip/><Bar dataKey="floor_value" stackId="range" fill="#27475a" name="Floor"/><Bar dataKey="range" stackId="range" fill="#64e8c4" name="Floor-to-ceiling width"/></BarChart></ResponsiveContainer></section>
    <NeedsHeatmap needs={needs} mode={mode} error={error}/>
    <PlayerTable players={players} title="All-player ownership matrix" eyebrow="League-aware player board" mode={mode}/>
  </div>;
}

function NeedsHeatmap({ needs, mode, error }: { needs: LeagueNeedsResponse | null; mode: DataMode; error?: string }) {
  const rows = needs?.needs ?? [];
  const positions = Array.from(new Set(rows.map((row) => row.position))).sort();
  const teams = Array.from(new Map(rows.map((row) => [row.roster_id, row.team_name ?? row.roster_id])).entries());
  return <section className="panel table-panel wide">
    <div className="panel-heading"><div><span className="eyebrow">Position heatmap</span><h2>Roster needs across the league</h2></div><ModeBadge mode={mode}/></div>
    {!rows.length ? <EmptyState message={error ? 'Position needs endpoint is unavailable.' : 'No roster-needs rows were returned.'}/> : <div className="table-scroll"><table className="heatmap-table"><thead><tr><th>Team</th>{positions.map((position) => <th key={position}>{position}</th>)}</tr></thead><tbody>{teams.map(([rosterId, teamName]) => <tr key={rosterId}><td><strong>{teamName}</strong></td>{positions.map((position) => {
      const item = rows.find((row) => row.roster_id === rosterId && row.position === position);
      const rawIntensity = item?.need_percentile ?? item?.need_score ?? 0;
      const intensity = Math.max(0, Math.min(1, rawIntensity > 1 ? rawIntensity / 100 : rawIntensity));
      return <td key={position}><span className="heat-cell" style={{ '--heat': intensity } as CSSProperties}>{item ? formatMetric(item.need_score, 2) : '—'}<small>{item?.need_rank ? `need #${item.need_rank}` : ''}</small></span></td>;
    })}</tr>)}</tbody></table></div>}
  </section>;
}

function PlayerView({ players, mode, decision, setDecision, error }: {
  players: PlayerRow[]; mode: DataMode; decision: DecisionType; setDecision: (decision: DecisionType) => void; error?: string;
}) {
  return <div className="page-grid">
    <section className="panel toolbar-panel wide"><div><span className="eyebrow">Rank multiverse</span><h2>One player, decision-specific value</h2><p>Changing the decision asks the Python engine for a new league-aware board; it does not rescale values in the browser.</p></div><label><span>Decision</span><select value={decision} onChange={(event) => setDecision(event.target.value as DecisionType)}>{decisions.map(([key, label]) => <option value={key} key={key}>{label}</option>)}</select></label></section>
    <PlayerTable players={players} title={`${decisions.find(([key]) => key === decision)?.[1]} rankings`} eyebrow="Overall and positional ranks" mode={mode} emptyMessage={error ? 'The player board endpoint is unavailable.' : undefined}/>
  </div>;
}

function TradeView({ trades, power, mode, error }: { trades: TradeSuggestion[]; power: PowerRanking[]; mode: DataMode; error?: string }) {
  const name = (rosterId: string) => power.find((team) => team.roster_id === rosterId)?.team_name ?? `Roster ${rosterId}`;
  return <div className="page-grid">
    <section className="panel trade-hero"><div className="badge-line"><span className="eyebrow">Mutual-benefit search</span><ModeBadge mode={mode}/></div><h2>Two-sided roster deltas</h2><p>Each proposal evaluates complete post-trade rosters and legal starting lineups. Positive value for one side does not erase cost to the other.</p></section>
    {!trades.length && <UnavailablePanel title="No trade frontier available" detail={error ? 'The trade suggestion endpoint did not return a usable response.' : 'No mutually eligible proposals cleared the backend filters.'}/>}
    {trades.map((trade, index) => <section className="panel trade-card expanded" key={index}>
      <div className="trade-card-head"><div className="trade-score"><span>{trade.analysis.fairness_score.toFixed(0)}</span><small>fairness</small></div><div><h3>{trade.analysis.verdict.replaceAll('_', ' ')}</h3><p>{trade.explanation}</p></div></div>
      <div className="trade-sides">
        <TradeDelta side={trade.analysis.side_a} name={name(trade.analysis.side_a.roster_id)}/>
        <TradeDelta side={trade.analysis.side_b} name={name(trade.analysis.side_b.roster_id)}/>
      </div>
      <div className="trade-confidence">Mutual benefit {trade.analysis.mutual_benefit_score.toFixed(0)}/100 · confidence {Math.round(trade.analysis.confidence * 100)}%</div>
    </section>)}
  </div>;
}

function TradeDelta({ side, name }: { side: TradeSide; name: string }) {
  const values = [
    ['Roster', side.value_delta], ['Starters', side.starter_delta], ['Floor', side.floor_delta],
    ['Ceiling', side.ceiling_delta], ['Depth', side.depth_delta],
  ] as const;
  return <div className="trade-side"><strong>{name}</strong>{values.map(([label, amount]) => <div className="delta-row" key={label}><span>{label}</span><div><i className={Number(amount ?? 0) >= 0 ? 'positive' : 'negative'} style={{ width: `${Math.min(100, Math.abs(Number(amount ?? 0)) * 10)}%` }}/></div><b>{signed(amount)}</b></div>)}<small>{side.reasons.join(' · ')}</small></div>;
}

function WaiverView({ players, mode, error }: { players: PlayerRow[]; mode: DataMode; error?: string }) {
  return <div className="page-grid">
    <section className="panel waiver-summary wide"><div className="panel-heading"><div><span className="eyebrow">Action shortlist</span><h2>Roster-relative upgrades and budget</h2></div><ModeBadge mode={mode}/></div><div className="mini-card-grid">{players.slice(0, 3).map((player) => <article key={player.player_id}><span className={`position-tag ${player.position.toLowerCase()}`}>{player.position}</span><div><strong>{player.player_name}</strong><small>{signed(player.waiver_upgrade)} upgrade · {player.faab_recommendation !== undefined ? `${player.faab_recommendation.toFixed(0)} FAAB` : 'FAAB unavailable'}</small></div></article>)}{!players.length && <EmptyState message={error ? 'Waiver endpoint unavailable.' : 'No eligible free agents were returned.'}/>}</div></section>
    <PlayerTable players={players} title="Opportunity Wire" eyebrow="GET /waivers · roster-relative" mode={mode} defaultSortKey="endpoint_order" emptyMessage={error ? 'Waiver endpoint unavailable.' : undefined}/>
  </div>;
}

function LineupView({ players, mode, error }: { players: PlayerRow[]; mode: DataMode; error?: string }) {
  const projected = players.reduce((sum, player) => sum + (player.fantasy_points_ppr_q50 ?? 0), 0);
  const swaps = players.filter((player) => player.lineup_delta !== undefined || player.replaces_player_name || player.is_current_starter === false);
  return <div className="page-grid">
    <section className="panel lineup-delta wide"><div className="panel-heading"><div><span className="eyebrow">Legal assignment optimizer</span><h2>Recommended lineup · {projected.toFixed(1)} q50 points</h2></div><ModeBadge mode={mode}/></div>
      {swaps.length ? <div className="swap-grid">{swaps.map((player) => <article key={player.player_id}><span>SWAP IN</span><strong>{player.player_name}</strong><small>for {player.replaces_player_name ?? 'current starter'} · {signed(player.lineup_delta)} q50</small></article>)}</div> : <p className="muted">{error ? 'Lineup endpoint unavailable.' : 'The optimized slots are shown below. Swap deltas require the imported platform snapshot to identify its submitted starters; no baseline comparison was returned.'}</p>}
    </section>
    <PlayerTable players={players} title="Optimized starting lineup" eyebrow="GET /lineup · legal slots" mode={mode} defaultSortKey="endpoint_order" showLineup emptyMessage={error ? 'Lineup endpoint unavailable.' : undefined}/>
  </div>;
}

function NFLView({ nflState, context, stateError, contextError }: { nflState: NFLStateSnapshot; context: TeamContextResponse | null; stateError?: string; contextError?: string }) {
  const stateMode = normalizeDataMode(nflState.data_mode, 'unverified');
  const stateTitle = stateMode === 'synthetic'
    ? 'Synthetic standings fixture'
    : stateMode === 'unverified'
      ? 'Standings unavailable or unverified'
      : 'Observed team results';
  const contextRows = context?.teams ?? [];
  const latestSeason = Math.max(0, ...contextRows.map((team) => Number(team.season ?? 0)));
  const seasonRows = contextRows.filter((team) => Number(team.season ?? 0) === latestSeason);
  const weekCoverage = new Map<number, Set<string>>();
  seasonRows.forEach((team) => {
    const week = Number(team.week ?? 0);
    const teams = weekCoverage.get(week) ?? new Set<string>();
    teams.add(String(team.recent_team ?? team.team ?? ''));
    weekCoverage.set(week, teams);
  });
  const fullSlateSize = Math.max(0, ...Array.from(weekCoverage.values(), (teams) => teams.size));
  const latestWeek = Math.max(0, ...Array.from(weekCoverage.entries())
    .filter(([, teams]) => teams.size === fullSlateSize)
    .map(([week]) => week));
  const latest = seasonRows.filter((team) => Number(team.week ?? 0) === latestWeek);
  const contextChart = latest.map((team) => ({
    team: team.recent_team ?? team.team,
    plays: Number(team.team_plays_roll4 ?? 0),
    neutralPass: Number(team.team_neutral_pass_rate_roll4 ?? 0) * 100,
  })).sort((a, b) => b.plays - a.plays);
  return <div className="page-grid">
    <section className="panel narrative-panel wide"><div className="badge-line"><span className="eyebrow">NFL standings · Week {nflState.week ?? '—'}</span><ModeBadge mode={stateMode}/></div><h2>{stateTitle}</h2><p>{stateError ? 'The standings endpoint failed closed because verified schedule provenance was unavailable.' : 'Records and point differential use the schedule provenance reported by the standings endpoint.'} Scheme fingerprints are shown separately only when leakage-safe lagged features are available.</p></section>
    <section className="panel chart-panel wide"><div className="panel-heading"><div><span className="eyebrow">Observed results</span><h2>Point differential</h2></div></div>{nflState.teams.length ? <ResponsiveContainer width="100%" height={320}><BarChart data={nflState.teams}><CartesianGrid strokeDasharray="3 3" stroke="#1d3042"/><XAxis dataKey="team" stroke="#7790a5"/><YAxis stroke="#7790a5"/><Tooltip/><Bar dataKey="point_differential" fill="#a78bfa"/></BarChart></ResponsiveContainer> : <EmptyState message="No provenance-verified standings were returned."/>}</section>
    <section className="panel chart-panel wide"><div className="panel-heading"><div><span className="eyebrow">Latest full-team historical slate · {fullSlateSize} teams</span><h2>Team fingerprints entering {latestSeason || '—'} Week {latestWeek || '—'}</h2></div><ModeBadge mode="historical"/></div>{contextChart.length ? <ResponsiveContainer width="100%" height={340}><BarChart data={contextChart}><CartesianGrid strokeDasharray="3 3" stroke="#1d3042"/><XAxis dataKey="team" stroke="#7790a5"/><YAxis stroke="#7790a5"/><Tooltip/><Bar dataKey="plays" fill="#64e8c4" name="Four-week plays"/><Bar dataKey="neutralPass" fill="#a78bfa" name="Neutral pass rate %"/></BarChart></ResponsiveContainer> : <EmptyState message={contextError ? 'Historical team-context artifact is unavailable.' : 'No lagged team-context rows were returned.'}/>}</section>
    <section className="panel table-panel wide"><div className="panel-heading"><div><span className="eyebrow">League table</span><h2>NFL records</h2></div></div><div className="table-scroll"><table><thead><tr><th>Team</th><th>Record</th><th>Win %</th><th>PF</th><th>PA</th><th>Diff</th><th>Streak</th></tr></thead><tbody>{nflState.teams.map(team => <tr key={team.team}><td><strong>{team.team}</strong></td><td>{team.wins}-{team.losses}-{team.ties}</td><td>{(team.win_percentage * 100).toFixed(1)}%</td><td>{team.points_for.toFixed(0)}</td><td>{team.points_against.toFixed(0)}</td><td>{team.point_differential > 0 ? '+' : ''}{team.point_differential.toFixed(0)}</td><td>{team.streak ?? '—'}</td></tr>)}</tbody></table></div></section>
  </div>;
}

function ModelView({ research, error }: { research: ResearchSummary | null; error?: string }) {
  const [season, setSeason] = useState('2025');
  const [week, setWeek] = useState('18');
  const [position, setPosition] = useState('ALL');
  const [predictions, setPredictions] = useState<ResearchPrediction[]>([]);
  const [replayError, setReplayError] = useState<string>();
  const seasons = [2021, 2022, 2023, 2024, 2025];
  const weeks = Array.from({ length: 18 }, (_, index) => index + 1);
  const positions = ['QB', 'RB', 'WR', 'TE'];

  useEffect(() => {
    setReplayError(undefined);
    api.researchPredictions(
      Number(season),
      Number(week),
      position === 'ALL' ? undefined : position,
      1000,
    )
      .then((payload) => setPredictions(payload.predictions ?? []))
      .catch((requestError) => {
        setPredictions([]);
        setReplayError(statusMessage(requestError));
      });
  }, [position, season, week]);

  const visible = predictions.filter((row) => (
    position === 'ALL' || row.position === position
  )).sort((a, b) => (a.overall_rank ?? Infinity) - (b.overall_rank ?? Infinity));
  const pprBenchmark = research?.benchmark.find((row) => text(row, ['target']) === 'fantasy_points_ppr' && text(row, ['method']) === 'quantile_engine')
    ?? research?.benchmark.find((row) => text(row, ['target']) === 'fantasy_points_ppr');
  const pprConformal = research?.conformal.find((row) => text(row, ['target']) === 'fantasy_points_ppr');
  const frozenBaseline = research?.frozen_opportunity.find((row) => text(row, ['method']) === 'numerical_baseline');
  const actualSourceBest = [...(research?.historical_sources ?? [])]
    .filter((row) => {
      const method = text(row, ['method']) ?? '';
      return method !== 'numerical_baseline' && !method.includes('control');
    })
    .sort((a, b) => (value(b, ['pinball_improvement_vs_baseline_pct']) ?? -Infinity)
      - (value(a, ['pinball_improvement_vs_baseline_pct']) ?? -Infinity))[0];
  const experiments = [
    ...(research?.historical_sources ?? []).map((row) => ({ family: `Actual source · ${text(row, ['method']) ?? 'experiment'}`, row })),
    ...(research?.frozen_opportunity ?? []).map((row) => ({ family: text(row, ['method']) ?? 'Opportunity experiment', row })),
    ...(research?.conformal ?? []).map((row) => ({ family: `${text(row, ['target']) ?? 'Target'} calibration`, row })),
  ];
  const coverageFamilies = Array.from(new Set(
    (research?.historical_source_coverage ?? []).map((row) => text(row, ['source_family'])).filter(Boolean),
  )).map((family) => {
    const rows = (research?.historical_source_coverage ?? []).filter((row) => text(row, ['source_family']) === family);
    const explicitRates = rows.map((row) => value(row, ['explicit_evidence_match_rate'])).filter((rate): rate is number => rate !== undefined);
    const idRates = rows.map((row) => value(row, ['id_resolution_rate'])).filter((rate): rate is number => rate !== undefined);
    return {
      family: family!,
      seasons: rows.length,
      explicitLow: explicitRates.length ? Math.min(...explicitRates) : undefined,
      explicitHigh: explicitRates.length ? Math.max(...explicitRates) : undefined,
      idLow: idRates.length ? Math.min(...idRates) : undefined,
      idHigh: idRates.length ? Math.max(...idRates) : undefined,
      statuses: Array.from(new Set(rows.map((row) => text(row, ['source_status'])).filter(Boolean))).join(', '),
    };
  });
  return <div className="page-grid">
    <div className="metric-grid wide">
      <Metric icon={FlaskConical} label="PPR pinball" value={formatMetric(value(pprBenchmark, ['engine_mean_pinball', 'mean_pinball']))} note="real OOS quantile engine"/>
      <Metric icon={Activity} label="PPR q50 MAE" value={formatMetric(value(pprBenchmark, ['engine_mae', 'mae']), 2)} note="real held-out games"/>
      <Metric icon={Shield} label="Calibrated coverage" value={value(pprConformal, ['calibrated_coverage']) !== undefined ? `${(value(pprConformal, ['calibrated_coverage'])! * 100).toFixed(1)}%` : '—'} note="q10–q90 interval"/>
      <Metric icon={Bot} label="Opportunity baseline" value={formatMetric(value(frozenBaseline, ['mean_pinball']))} note="challengers gated"/>
      <Metric icon={Database} label="Best actual-source delta" value={value(actualSourceBest, ['pinball_improvement_vs_baseline_pct']) !== undefined ? `${signed(value(actualSourceBest, ['pinball_improvement_vs_baseline_pct']))}%` : '—'} note={text(actualSourceBest ?? {}, ['method'])?.replaceAll('_', ' ') ?? 'artifact unavailable'}/>
    </div>
    <section className="panel experiment-panel wide"><div className="panel-heading"><div><span className="eyebrow">Coverage before performance</span><h2>Historical source quality by family</h2></div><ModeBadge mode="historical"/></div>
      {!coverageFamilies.length ? <EmptyState message="Actual-source coverage artifact is unavailable."/> : <div className="experiment-grid">{coverageFamilies.map((item) => <article key={item.family}><span className="experiment-status evaluated">{item.seasons} seasons</span><strong>{item.family.replaceAll('_', ' ')}</strong><small>Evidence {item.explicitLow === undefined ? '—' : `${(item.explicitLow * 100).toFixed(1)}–${(item.explicitHigh! * 100).toFixed(1)}%`} · IDs {item.idLow === undefined ? '—' : `${(item.idLow * 100).toFixed(1)}–${(item.idHigh! * 100).toFixed(1)}%`}</small><small>{item.statuses || 'status unavailable'}</small></article>)}</div>}
    </section>
    <section className="panel experiment-panel wide"><div className="panel-heading"><div><span className="eyebrow">Promotion gate</span><h2>Accepted, rejected, and controlled evidence</h2></div><ModeBadge mode="historical"/></div>
      {!experiments.length ? <EmptyState message={error ? 'Research summary artifacts are unavailable.' : 'No experiment rows were returned.'}/> : <div className="experiment-grid">{experiments.slice(0, 18).map(({ family, row }, index) => {
        const improvement = value(row, ['pinball_improvement_vs_baseline_pct', 'pinball_improvement_pct']);
        const method = text(row, ['method']) ?? '';
        const status = method === 'numerical_baseline' ? 'RETAIN' : method.includes('control') ? 'CONTROL' : improvement !== undefined && improvement < 0 ? 'REJECT' : 'EVALUATED';
        return <article key={`${family}-${index}`}><span className={`experiment-status ${status.toLowerCase()}`}>{status}</span><strong>{family.replaceAll('_', ' ')}</strong><small>{improvement === undefined ? 'Recorded frozen result' : `${improvement > 0 ? '+' : ''}${improvement.toFixed(2)}% pinball vs baseline`}</small></article>;
      })}</div>}
    </section>
    <section className="panel replay-panel wide">
      <div className="panel-heading"><div><span className="eyebrow">Frozen predictions</span><h2>Historical model replay</h2></div><ModeBadge mode="historical"/></div>
      <div className="board-controls replay-controls">
        <label>Season<select value={season} onChange={(event) => setSeason(event.target.value)}>{seasons.map((item) => <option key={item}>{item}</option>)}</select></label>
        <label>Week<select value={week} onChange={(event) => setWeek(event.target.value)}>{weeks.map((item) => <option key={item}>{item}</option>)}</select></label>
        <label>Position<select value={position} onChange={(event) => setPosition(event.target.value)}><option value="ALL">All</option>{positions.map((item) => <option key={item}>{item}</option>)}</select></label>
      </div>
      {!visible.length ? <EmptyState message={replayError || error ? 'Historical prediction artifact is unavailable.' : 'No frozen predictions match this season, week, and position.'}/> : <div className="table-scroll"><table><thead><tr><th>Ranks</th><th>Player</th><th>Season / week</th><th>Interval</th><th>Actual</th><th>Residual</th><th>Method</th></tr></thead><tbody>{visible.slice(0, 150).map((row, index) => <tr key={`${row.season}-${row.week}-${row.player_id}-${index}`}><td><strong>#{row.overall_rank ?? '—'}</strong><small className="rank-sub">{row.position}{row.position_rank ?? '—'}</small></td><td><strong>{row.player_name}</strong><small className="rank-sub">{row.team ?? row.recent_team ?? row.position}</small></td><td>{row.season} · W{row.week}</td><td>{formatMetric(row.q10, 1)} / <strong>{formatMetric(row.q50, 1)}</strong> / {formatMetric(row.q90, 1)}</td><td>{formatMetric(row.actual ?? undefined, 1)}</td><td>{row.actual !== null && row.actual !== undefined && row.q50 !== undefined ? signed(row.actual - row.q50) : '—'}</td><td>{row.method ?? 'frozen model'}</td></tr>)}</tbody></table></div>}
    </section>
  </div>;
}

function Metric({ icon: Icon, label, value: metricValue, note }: { icon: typeof Gauge; label: string; value: string; note: string }) {
  return <section className="metric-card"><div className="metric-icon"><Icon size={20}/></div><span>{label}</span><strong>{metricValue}</strong><small>{note}</small></section>;
}

function EmptyState({ message }: { message: string }) {
  return <div className="empty-state"><AlertTriangle size={18}/><span>{message}</span></div>;
}

function UnavailablePanel({ title, detail }: { title: string; detail: string }) {
  return <section className="panel unavailable-panel"><AlertTriangle size={22}/><div><span className="eyebrow">Evidence boundary</span><h2>{title}</h2><p>{detail}</p></div></section>;
}
