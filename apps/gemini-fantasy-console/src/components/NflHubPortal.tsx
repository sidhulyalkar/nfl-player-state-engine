import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity, AlertTriangle, ArrowUpRight, CalendarDays, CheckCircle2, Clock3,
  RefreshCw, Search, ShieldCheck, TrendingDown, TrendingUp, UsersRound,
} from 'lucide-react';
import {
  nflHubApi, type NflHubEvent, type NflHubPlayerState, type NflHubResponse,
} from '../lib/nflHubApi';
import '../nfl-hub.css';

const FILTERS = ['ALL', 'ROSTER', 'ROLE', 'INJURY', 'MARKET'] as const;
type Filter = typeof FILTERS[number];

function eventGroup(event: NflHubEvent): Exclude<Filter, 'ALL'> {
  if (event.event_type.includes('INJURY')) return 'INJURY';
  if (event.event_type.includes('DEPTH')) return 'ROLE';
  if (event.event_type.includes('MARKET')) return 'MARKET';
  return 'ROSTER';
}

function eventLabel(value: string) {
  return value.toLowerCase().replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function num(value: number | null | undefined, digits = 0) {
  return value == null || !Number.isFinite(value) ? '—' : value.toFixed(digits);
}

function ageLabel(seconds: number | null | undefined) {
  if (seconds == null || !Number.isFinite(seconds)) return 'age unknown';
  if (seconds < 60) return `${Math.round(seconds)} sec old`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min old`;
  return `${(seconds / 3600).toFixed(1)} hr old`;
}

function gameLabel(value: string | null | undefined) {
  if (!value) return 'Time unavailable';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString(undefined, { month: 'short', day: 'numeric', weekday: 'short' });
}

function workspaceHref(surface: 'draft' | 'intelligence', playerId?: string | null) {
  const params = new URLSearchParams(window.location.search);
  params.set('workspace', surface);
  if (playerId) params.set('player', playerId);
  else params.delete('player');
  return `${window.location.pathname}?${params.toString()}`;
}

function currentState(event: NflHubEvent): NflHubPlayerState | null {
  return event.after ?? event.before;
}

function EventIcon({ event }: { event: NflHubEvent }) {
  const group = eventGroup(event);
  if (group === 'MARKET') {
    return event.event_type.includes('RISER') ? <TrendingUp size={17}/> : <TrendingDown size={17}/>;
  }
  if (group === 'INJURY') return <Activity size={17}/>;
  if (group === 'ROLE') return <ArrowUpRight size={17}/>;
  return <UsersRound size={17}/>;
}

export function NflHubPortal() {
  const [hub, setHub] = useState<NflHubResponse | null>(null);
  const [filter, setFilter] = useState<Filter>('ALL');
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const request = useRef<AbortController | null>(null);
  const attemptedAutoRefresh = useRef(false);

  const load = useCallback(async (forceRefresh: boolean) => {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setLoading(true);
    try {
      const payload = forceRefresh
        ? await nflHubApi.refresh(controller.signal)
        : await nflHubApi.snapshot(controller.signal);
      if (controller.signal.aborted) return;
      setHub(payload);
      setError(payload.refresh_warning);
      if (!forceRefresh && payload.cache.stale && !attemptedAutoRefresh.current) {
        attemptedAutoRefresh.current = true;
        void load(true);
      }
    } catch (reason) {
      if (controller.signal.aborted) return;
      if (!forceRefresh && !attemptedAutoRefresh.current) {
        attemptedAutoRefresh.current = true;
        void load(true);
        return;
      }
      setError(reason instanceof Error ? reason.message : 'NFL Hub unavailable');
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(false);
    return () => request.current?.abort();
  }, [load]);

  const visibleEvents = useMemo(() => {
    const term = search.trim().toLowerCase();
    return (hub?.events ?? []).filter((event) => {
      if (filter !== 'ALL' && eventGroup(event) !== filter) return false;
      if (!term) return true;
      const state = currentState(event);
      return `${event.player_name ?? ''} ${state?.team ?? ''} ${state?.position ?? ''} ${event.detail}`
        .toLowerCase().includes(term);
    });
  }, [filter, hub, search]);

  const counts = useMemo(() => {
    const output: Record<Filter, number> = { ALL: hub?.event_count ?? 0, ROSTER: 0, ROLE: 0, INJURY: 0, MARKET: 0 };
    (hub?.events ?? []).forEach((event) => { output[eventGroup(event)] += 1; });
    return output;
  }, [hub]);

  const sourceHealthy = hub?.source_health.filter((source) => source.available).length ?? 0;
  const sourceTotal = hub?.source_health.length ?? 0;
  const topEvents = (hub?.events ?? []).slice(0, 4);

  return <div className="nfl-hub-root">
    <header className="nfl-hub-header">
      <div>
        <span className="nfl-hub-eyebrow">NFL STATE · 2026</span>
        <h1>What changed, and why does it matter?</h1>
        <p>Roster truth, depth movement, injuries, draft-market movement and schedule context. Observations stay separate from model authority.</p>
      </div>
      <div className="nfl-hub-header-actions">
        <div className={`nfl-hub-state ${(hub?.status ?? 'loading').toLowerCase()}`}>
          <i/>
          <span>{hub?.status ?? 'CONNECTING'}</span>
          <small>{ageLabel(hub?.cache.snapshot_age_seconds)}</small>
        </div>
        <button onClick={() => void load(true)} disabled={loading}>
          <RefreshCw size={15} className={loading ? 'spin' : ''}/> Refresh NFL truth
        </button>
      </div>
    </header>

    {error && <div className="nfl-hub-warning"><AlertTriangle size={16}/><span>{error}</span></div>}

    <section className="nfl-hub-summary-grid">
      <div className="nfl-hub-summary primary">
        <span>Changes since prior snapshot</span>
        <strong>{hub?.event_count ?? '—'}</strong>
        <small>{hub?.event_count ? `${topEvents.length} highest-impact changes surfaced first` : 'Refreshes are compared against the last good snapshot.'}</small>
      </div>
      <div className="nfl-hub-summary">
        <span>Rostered players tracked</span>
        <strong>{hub?.player_count ?? '—'}</strong>
        <small>GSIS-linked current roster state</small>
      </div>
      <div className="nfl-hub-summary">
        <span>Source health</span>
        <strong>{hub ? `${sourceHealthy}/${sourceTotal}` : '—'}</strong>
        <small>{hub?.optional_source_failures.length ? `${hub.optional_source_failures.join(', ')} degraded` : 'All configured sources reporting'}</small>
      </div>
      <div className="nfl-hub-summary">
        <span>Upcoming games</span>
        <strong>{hub?.upcoming_games.length ?? '—'}</strong>
        <small>Preseason / regular-season schedule context</small>
      </div>
    </section>

    <section className="nfl-hub-impact-strip">
      <div className="nfl-hub-section-heading">
        <div><span>RIGHT NOW</span><h2>Highest-impact movement</h2></div>
        <small>Observed state changes, not automatic model adjustments.</small>
      </div>
      <div className="nfl-hub-impact-grid">
        {topEvents.length ? topEvents.map((event) => {
          const state = currentState(event);
          return <article key={`${event.event_type}:${event.player_id}:${event.detail}`}>
            <div className={`nfl-hub-event-icon ${eventGroup(event).toLowerCase()}`}><EventIcon event={event}/></div>
            <div className="nfl-hub-impact-copy">
              <span>{eventLabel(event.event_type)}</span>
              <strong>{event.player_name ?? event.player_id ?? 'NFL change'}</strong>
              <p>{event.detail}</p>
              <small>{state?.position ?? '—'} · {state?.team ?? '—'} · significance {Math.round(event.significance * 100)}</small>
            </div>
            {event.player_id && <a href={workspaceHref('intelligence', event.player_id)}>Inspect <ArrowUpRight size={13}/></a>}
          </article>;
        }) : <div className="nfl-hub-empty"><CheckCircle2 size={20}/><strong>No state changes recorded yet</strong><span>The first successful refresh establishes a baseline. The next refresh will expose deltas.</span></div>}
      </div>
    </section>

    <div className="nfl-hub-layout">
      <main className="nfl-hub-panel nfl-hub-feed">
        <div className="nfl-hub-section-heading feed-heading">
          <div><span>CHANGE LEDGER</span><h2>Everything that moved</h2></div>
          <div className="nfl-hub-search"><Search size={14}/><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Player, team, change"/></div>
        </div>
        <div className="nfl-hub-filters">{FILTERS.map((item) => <button key={item} className={filter === item ? 'active' : ''} onClick={() => setFilter(item)}>{item}<small>{counts[item]}</small></button>)}</div>
        <div className="nfl-hub-events">
          {visibleEvents.map((event) => {
            const state = currentState(event);
            return <article className="nfl-hub-event" key={`${event.event_type}:${event.player_id}:${event.detail}`}>
              <div className={`nfl-hub-event-icon ${eventGroup(event).toLowerCase()}`}><EventIcon event={event}/></div>
              <div className="nfl-hub-event-main">
                <div><span>{eventLabel(event.event_type)}</span><small>{state?.position ?? '—'} · {state?.team ?? '—'}</small></div>
                <strong>{event.player_name ?? event.player_id ?? 'NFL state change'}</strong>
                <p>{event.detail}</p>
              </div>
              <div className="nfl-hub-context">
                <span>Model context</span>
                <strong>{num(state?.projection_q50)} <small>q50</small></strong>
                <small>VORP {num(state?.projection_vorp, 1)} · ADP {num(state?.market_adp, 1)}</small>
              </div>
              <div className="nfl-hub-event-actions">
                {event.player_id && <a href={workspaceHref('intelligence', event.player_id)}>Player <ArrowUpRight size={12}/></a>}
                <a href={workspaceHref('draft')}>Draft room</a>
              </div>
            </article>;
          })}
          {!visibleEvents.length && <div className="nfl-hub-empty compact"><span>No changes match this view.</span></div>}
        </div>
      </main>

      <aside className="nfl-hub-side">
        <section className="nfl-hub-panel">
          <div className="nfl-hub-section-heading compact"><div><span>SCHEDULE</span><h2>What is next</h2></div><CalendarDays size={18}/></div>
          <div className="nfl-hub-games">{(hub?.upcoming_games ?? []).slice(0, 8).map((game, index) => <div key={game.game_id ?? `${game.away_team}:${game.home_team}:${index}`}>
            <span>{game.game_type ?? 'NFL'} · W{game.week ?? '—'}</span>
            <strong>{game.away_team ?? 'TBD'} <i>@</i> {game.home_team ?? 'TBD'}</strong>
            <small>{gameLabel(game.game_date)}</small>
          </div>)}</div>
          {!hub?.upcoming_games.length && <p className="nfl-hub-muted">Schedule source unavailable or no future games in the current snapshot.</p>}
        </section>

        <section className="nfl-hub-panel">
          <div className="nfl-hub-section-heading compact"><div><span>PROVENANCE</span><h2>Source health</h2></div><ShieldCheck size={18}/></div>
          <div className="nfl-hub-sources">{(hub?.source_health ?? []).map((source) => <div key={source.source}>
            <i className={source.available ? 'ok' : 'bad'}/>
            <span><strong>{source.source.replaceAll('_', ' ')}</strong><small>{source.available ? `${source.rows} rows` : source.error ?? 'Unavailable'}</small></span>
            <em>{source.required ? 'CORE' : 'OPTIONAL'}</em>
          </div>)}</div>
          <p className="nfl-hub-authority"><Clock3 size={14}/>{hub?.model_note ?? 'NFL Hub observations do not promote model authority.'}</p>
        </section>
      </aside>
    </div>
  </div>;
}
