import type { ChangeEvent } from 'react';
import { useEffect, useMemo, useState } from 'react';
import { Activity, BarChart3, Bot, CircleDollarSign, FlaskConical, Gauge, LayoutDashboard, Repeat2, Search, Shield, Trophy, Users } from 'lucide-react';
import { Area, AreaChart, Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { LeagueSummary, NFLStateSnapshot, NavPage, PlayerRow, PowerRanking, TradeSuggestion } from '../shared/types';
import { Copilot } from './components/Copilot';
import { PlayerTable } from './components/PlayerTable';
import { api } from './lib/api';
import { demoNFL, demoPlayers, demoPower, demoTrades } from './lib/demo';
import './styles.css';

const nav: Array<[NavPage, string, typeof LayoutDashboard]> = [
  ['overview', 'Command Center', LayoutDashboard], ['league', 'League Picture', Users],
  ['players', 'Player Lab', Search], ['trade', 'Trade Lab', Repeat2],
  ['waivers', 'Opportunity Wire', Activity], ['lineup', 'Lineup Lab', Shield],
  ['nfl', 'NFL State', Trophy], ['model', 'Model Lab', FlaskConical],
];

export default function App() {
  const [page, setPage] = useState<NavPage>('overview');
  const [leagues, setLeagues] = useState<LeagueSummary[]>([]);
  const [leagueId, setLeagueId] = useState('demo-league');
  const [rosterId, setRosterId] = useState('1');
  const [players, setPlayers] = useState<PlayerRow[]>(demoPlayers);
  const [power, setPower] = useState<PowerRanking[]>(demoPower);
  const [trades, setTrades] = useState<TradeSuggestion[]>(demoTrades);
  const [nflState, setNflState] = useState<NFLStateSnapshot>(demoNFL);
  const [status, setStatus] = useState('Demo mode');

  useEffect(() => {
    api.leagues().then((items) => {
      if (!items.length) return;
      setLeagues(items); setLeagueId(items[0].league_id); setStatus('Connected to PSE API');
    }).catch(() => setStatus('Demo mode · connect PSE API to activate live leagues'));
  }, []);

  useEffect(() => {
    if (leagueId === 'demo-league') return;
    Promise.all([api.players(leagueId), api.powerRankings(leagueId), api.tradeSuggestions(leagueId, rosterId), api.nflState(2026)])
      .then(([newPlayers, newPower, newTrades, newNFLState]) => { setPlayers(newPlayers); setPower(newPower); setTrades(newTrades); setNflState(newNFLState); })
      .catch(() => undefined);
  }, [leagueId, rosterId]);

  const freeAgents = useMemo(() => players.filter((player) => player.is_free_agent).slice(0, 12), [players]);
  const myPlayers = useMemo(() => players.filter((player) => player.owner_roster_id === rosterId).slice(0, 14), [players, rosterId]);
  const selectedPower = power.find((team) => team.roster_id === rosterId) ?? power[0];
  const trend = Array.from({ length: 8 }, (_, index) => ({ week: `W${index + 1}`, projection: 118 + index * 2 + Math.sin(index) * 9, actual: 114 + index * 3 + Math.cos(index) * 11 }));

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand"><div className="brand-mark">4D</div><div><strong>Fourth Down Lab</strong><small>Player State Engine</small></div></div>
        <nav>{nav.map(([key, label, Icon]) => <button key={key} className={page === key ? 'active' : ''} onClick={() => setPage(key)}><Icon size={18}/>{label}</button>)}</nav>
        <div className="sidebar-foot"><span className="status-dot"/><div><strong>{status}</strong><small>Model truth stays server-side</small></div></div>
      </aside>
      <main>
        <header className="topbar">
          <div><span className="eyebrow">League intelligence operating system</span><h1>{nav.find(([key]) => key === page)?.[1]}</h1></div>
          <div className="top-actions">
            <select value={leagueId} onChange={(event: ChangeEvent<HTMLSelectElement>) => setLeagueId(event.target.value)}>
              <option value="demo-league">Demo League</option>{leagues.map((league) => <option key={league.league_id} value={league.league_id}>{league.name}</option>)}
            </select>
            <select value={rosterId} onChange={(event: ChangeEvent<HTMLSelectElement>) => setRosterId(event.target.value)}>{power.map((team) => <option key={team.roster_id} value={team.roster_id}>{team.team_name}</option>)}</select>
            <Copilot leagueId={leagueId} rosterId={rosterId}/>
          </div>
        </header>

        {page === 'overview' && <div className="page-grid">
          <section className="hero-card">
            <div><span className="eyebrow">Your team state</span><h2>{selectedPower?.team_name ?? 'Neural Blitz'}</h2><p>Projected as a contender with one fragile RB slot and above-average weekly ceiling.</p></div>
            <div className="hero-score"><span>{selectedPower?.power_score.toFixed(0) ?? 91}</span><small>power</small></div>
          </section>
          <div className="metric-grid">
            <Metric icon={Gauge} label="Roster value" value={selectedPower?.roster_value.toFixed(0) ?? '364'} note="league adjusted"/>
            <Metric icon={Shield} label="Floor" value={selectedPower?.floor_value.toFixed(0) ?? '280'} note="10th percentile"/>
            <Metric icon={BarChart3} label="Ceiling" value={selectedPower?.ceiling_value.toFixed(0) ?? '438'} note="90th percentile"/>
            <Metric icon={Activity} label="Risk" value={`${selectedPower?.risk_score.toFixed(0) ?? 44}%`} note="roster uncertainty"/>
          </div>
          <section className="panel chart-panel"><div className="panel-heading"><div><span className="eyebrow">Calibration-aware</span><h2>Team trajectory</h2></div></div><ResponsiveContainer width="100%" height={260}><AreaChart data={trend}><defs><linearGradient id="projection" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#64e8c4" stopOpacity={0.5}/><stop offset="95%" stopColor="#64e8c4" stopOpacity={0}/></linearGradient></defs><CartesianGrid strokeDasharray="3 3" stroke="#1d3042"/><XAxis dataKey="week" stroke="#7790a5"/><YAxis stroke="#7790a5"/><Tooltip/><Area type="monotone" dataKey="projection" stroke="#64e8c4" fill="url(#projection)"/><Area type="monotone" dataKey="actual" stroke="#a78bfa" fillOpacity={0}/></AreaChart></ResponsiveContainer></section>
          <section className="panel rankings"><div className="panel-heading"><div><span className="eyebrow">Complete league picture</span><h2>Power rankings</h2></div></div>{power.map((team, index) => <div className="ranking-row" key={team.roster_id}><span className="rank-number">{index + 1}</span><div><strong>{team.team_name}</strong><small>{team.record}</small></div><div className="rank-bar"><span style={{ width: `${team.power_score}%` }}/></div><strong>{team.power_score.toFixed(0)}</strong></div>)}</section>
          <PlayerTable players={freeAgents} title="Highest-leverage free agents"/>
        </div>}

        {page === 'league' && <div className="page-grid"><section className="panel chart-panel wide"><div className="panel-heading"><div><span className="eyebrow">Roster strength by manager</span><h2>League topology</h2></div></div><ResponsiveContainer width="100%" height={360}><BarChart data={power}><CartesianGrid strokeDasharray="3 3" stroke="#1d3042"/><XAxis dataKey="team_name" stroke="#7790a5"/><YAxis stroke="#7790a5"/><Tooltip/><Bar dataKey="floor_value" stackId="a" fill="#27475a"/><Bar dataKey="roster_value" stackId="a" fill="#64e8c4"/></BarChart></ResponsiveContainer></section><PlayerTable players={players} title="All-player ownership matrix"/></div>}
        {page === 'players' && <div className="page-grid"><PlayerTable players={players} title="Player state explorer"/><section className="panel narrative-panel"><span className="eyebrow">Player cards should answer</span><h2>What changed, why, and how certain are we?</h2><ul><li>Active probability and workload restrictions</li><li>Snap, route, carry, target, and red-zone ladder</li><li>Opponent structure and game-script distributions</li><li>Floor, median, ceiling, and scenario sensitivity</li><li>League ownership, replacement value, and trade cost</li></ul></section></div>}
        {page === 'trade' && <div className="page-grid"><section className="panel trade-hero"><span className="eyebrow">Mutual-benefit search</span><h2>Trade Lab</h2><p>Evaluate both teams before and after the trade, including legal lineups, positional scarcity, depth, floor, ceiling, and probability of improvement.</p></section>{trades.map((trade, index) => <section className="panel trade-card" key={index}><div className="trade-score"><span>{trade.analysis.fairness_score.toFixed(0)}</span><small>fairness</small></div><div><h3>{trade.analysis.verdict.replace('_', ' ')}</h3><p>{trade.explanation}</p><div className="trade-deltas"><span>Your gain <strong>+{trade.analysis.side_a.value_delta.toFixed(1)}</strong></span><span>Their gain <strong>+{trade.analysis.side_b.value_delta.toFixed(1)}</strong></span><span>Confidence <strong>{Math.round(trade.analysis.confidence * 100)}%</strong></span></div></div></section>)}</div>}
        {page === 'waivers' && <PlayerTable players={freeAgents} title="Opportunity Wire"/>}
        {page === 'lineup' && <div className="page-grid"><PlayerTable players={myPlayers} title="Optimized roster candidates"/><section className="panel narrative-panel"><span className="eyebrow">Scenario controls</span><h2>Build for your matchup</h2><p>Choose floor when favored, ceiling when chasing, then simulate correlated game outcomes rather than selecting the highest point estimate at every slot.</p></section></div>}
        {page === 'nfl' && <div className="page-grid"><section className="panel narrative-panel wide"><span className="eyebrow">NFL state layer · Week {nflState.week ?? '—'}</span><h2>Teams, games, systems, and injuries</h2><p>The production view combines standings, point differential, dynamic team strength, coaching tendencies, pace, neutral pass rate, personnel usage, injury density, and projected game environments.</p></section><section className="panel chart-panel wide"><ResponsiveContainer width="100%" height={340}><BarChart data={nflState.teams}><CartesianGrid strokeDasharray="3 3" stroke="#1d3042"/><XAxis dataKey="team" stroke="#7790a5"/><YAxis stroke="#7790a5"/><Tooltip/><Bar dataKey="point_differential" fill="#a78bfa"/></BarChart></ResponsiveContainer></section><section className="panel table-panel wide"><div className="panel-heading"><div><span className="eyebrow">League table</span><h2>NFL records</h2></div></div><div className="table-scroll"><table><thead><tr><th>Team</th><th>Record</th><th>Win %</th><th>PF</th><th>PA</th><th>Diff</th><th>Streak</th></tr></thead><tbody>{nflState.teams.map(team => <tr key={team.team}><td><strong>{team.team}</strong></td><td>{team.wins}-{team.losses}-{team.ties}</td><td>{(team.win_percentage * 100).toFixed(1)}%</td><td>{team.points_for.toFixed(0)}</td><td>{team.points_against.toFixed(0)}</td><td>{team.point_differential > 0 ? '+' : ''}{team.point_differential.toFixed(0)}</td><td>{team.streak ?? '—'}</td></tr>)}</tbody></table></div></section></div>}
        {page === 'model' && <div className="page-grid"><div className="metric-grid wide"><Metric icon={FlaskConical} label="OOS seasons" value="5" note="2021–2025"/><Metric icon={Activity} label="PPR gain" value="5.76%" note="pinball vs rolling"/><Metric icon={Shield} label="Coverage" value="81.8%" note="nominal 80%"/><Metric icon={Bot} label="Soft intel" value="Off" note="requires promotion"/></div><section className="panel narrative-panel wide"><span className="eyebrow">Trust console</span><h2>Model cards inside the product</h2><p>Expose timestamp, model version, calibration, feature freshness, missing sources, baseline comparison, and reason codes beside every recommendation. An attractive interface should make uncertainty visible, not airbrush it.</p></section></div>}
      </main>
    </div>
  );
}

function Metric({ icon: Icon, label, value, note }: { icon: typeof Gauge; label: string; value: string; note: string }) {
  return <section className="metric-card"><div className="metric-icon"><Icon size={20}/></div><span>{label}</span><strong>{value}</strong><small>{note}</small></section>;
}
