import { useEffect, useMemo, useState } from 'react';
import { CheckCircle2, ChevronDown, ChevronUp, Link2, LockKeyhole, RefreshCw } from 'lucide-react';
import '../league-onboarding.css';

type ConnectionSummary = {
  league_id: string;
  name: string;
  platform: string;
  season: number;
  imported_at?: string;
};

type PortfolioState = {
  expected_league_count: number | null;
  connected_league_count: number;
  missing_league_count: number | null;
  complete: boolean;
  connections: ConnectionSummary[];
  ignored_non_real_snapshot_count: number;
  supported_platforms: string[];
  espn_private_auth_configured: boolean;
  credential_contract: string;
};

async function responseDetail(response: Response) {
  const text = await response.text();
  try {
    const payload = JSON.parse(text) as { detail?: string };
    return payload.detail ?? text;
  } catch {
    return text || response.statusText;
  }
}

export function LeagueOnboardingPanel() {
  const [portfolio, setPortfolio] = useState<PortfolioState | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [expectedDraft, setExpectedDraft] = useState('');
  const [platform, setPlatform] = useState<'sleeper' | 'espn'>('sleeper');
  const [leagueId, setLeagueId] = useState('');
  const [season, setSeason] = useState('2026');
  const [sleeperUser, setSleeperUser] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    const response = await fetch('/api/pse/v1/draft/connections');
    if (!response.ok) throw new Error(await responseDetail(response));
    const payload = await response.json() as PortfolioState;
    setPortfolio(payload);
    if (payload.expected_league_count != null) {
      setExpectedDraft(String(payload.expected_league_count));
    }
    if (!payload.complete) setExpanded(true);
  }

  useEffect(() => {
    void refresh().catch((reason) => {
      setError(reason instanceof Error ? reason.message : 'League connection status unavailable');
      setExpanded(true);
    });
  }, []);

  const countLabel = useMemo(() => {
    if (!portfolio) return 'checking';
    if (portfolio.expected_league_count == null) return `${portfolio.connected_league_count} connected`;
    return `${portfolio.connected_league_count}/${portfolio.expected_league_count} connected`;
  }, [portfolio]);

  async function saveExpectation() {
    const expected = Number(expectedDraft);
    if (!Number.isInteger(expected) || expected < 1 || expected > 20) {
      setError('Enter an intended league count between 1 and 20.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const response = await fetch('/api/pse/v1/draft/connections/expectation', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ expected_league_count: expected }),
      });
      if (!response.ok) throw new Error(await responseDetail(response));
      setPortfolio(await response.json() as PortfolioState);
      setMessage(`Draft portfolio set to ${expected} league${expected === 1 ? '' : 's'}.`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not save portfolio size');
    } finally {
      setBusy(false);
    }
  }

  async function connectLeague() {
    if (!/^\d+$/.test(leagueId.trim())) {
      setError('Enter the numeric league ID shown by Sleeper or ESPN.');
      return;
    }
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const response = await fetch('/api/pse/v1/draft/connections', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          platform,
          league_id: leagueId.trim(),
          season: Number(season),
          external_user_id: platform === 'sleeper' && sleeperUser.trim() ? sleeperUser.trim() : null,
          include_free_agents: true,
        }),
      });
      if (!response.ok) throw new Error(await responseDetail(response));
      const payload = await response.json() as { connection: { league_name: string }; portfolio: PortfolioState };
      setPortfolio(payload.portfolio);
      setLeagueId('');
      setMessage(`${payload.connection.league_name} connected and validated. Reloading the live board…`);
      window.setTimeout(() => window.location.reload(), 700);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'League connection failed');
    } finally {
      setBusy(false);
    }
  }

  return <section className={`league-onboarding ${portfolio?.complete ? 'complete' : 'incomplete'}`}>
    <div className="league-onboarding-head">
      <div className="league-onboarding-title"><Link2 size={17}/><div><span>REAL LEAGUES</span><strong>{countLabel}</strong></div></div>
      <div className="league-onboarding-state">
        {portfolio?.complete && <span className="portfolio-complete"><CheckCircle2 size={14}/>Portfolio complete</span>}
        <button onClick={() => setExpanded((value) => !value)}>{expanded ? <ChevronUp size={15}/> : <ChevronDown size={15}/>}Manage</button>
      </div>
    </div>

    {expanded && <div className="league-onboarding-body">
      <div className="portfolio-contract">
        <div><strong>How many real leagues should be here?</strong><span>The aggregate Draft-Day Doctor stays provisional until this is declared, then blocks if any intended league is missing.</span></div>
        <input inputMode="numeric" value={expectedDraft} onChange={(event) => setExpectedDraft(event.target.value)} placeholder="3" aria-label="Expected draft league count"/>
        <button onClick={() => void saveExpectation()} disabled={busy}>Save count</button>
      </div>

      {(portfolio?.connections.length ?? 0) > 0 && <div className="connected-leagues">
        {portfolio?.connections.map((connection) => <div key={`${connection.platform}:${connection.league_id}`}><span>{connection.platform.toUpperCase()}</span><strong>{connection.name}</strong><small>{connection.season} · {connection.league_id}</small></div>)}
      </div>}

      <div className="connect-form">
        <div className="connect-copy"><strong>Connect a league</strong><span>Imports the platform's real rules, rosters and draft state, validates them, then atomically stores one normalized snapshot.</span></div>
        <label><span>Platform</span><select value={platform} onChange={(event) => setPlatform(event.target.value as 'sleeper' | 'espn')}><option value="sleeper">Sleeper</option><option value="espn">ESPN</option></select></label>
        <label><span>League ID</span><input value={leagueId} onChange={(event) => setLeagueId(event.target.value)} placeholder="numeric league ID"/></label>
        <label><span>Season</span><input inputMode="numeric" value={season} onChange={(event) => setSeason(event.target.value)}/></label>
        {platform === 'sleeper' && <label><span>Your Sleeper user ID <small>optional</small></span><input value={sleeperUser} onChange={(event) => setSleeperUser(event.target.value)} placeholder="for automatic team selection"/></label>}
        <button className="connect-button" onClick={() => void connectLeague()} disabled={busy}>{busy ? <RefreshCw size={15} className="spin"/> : <Link2 size={15}/>}Connect</button>
      </div>

      {platform === 'espn' && <div className={`credential-note ${portfolio?.espn_private_auth_configured ? 'configured' : ''}`}><LockKeyhole size={15}/><span>{portfolio?.espn_private_auth_configured ? 'Private ESPN authentication is configured on the API server.' : 'Public ESPN leagues can connect now. Private leagues require PSE_ESPN_S2 and PSE_ESPN_SWID in the server environment.'} No cookie value is accepted by or returned to this browser.</span></div>}
      {message && <div className="connect-message success">{message}</div>}
      {error && <div className="connect-message error">{error}</div>}
    </div>}
  </section>;
}
