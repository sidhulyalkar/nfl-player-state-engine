import { useCallback, useEffect, useRef, useState } from 'react';
import { Activity, AlertTriangle, Bell, Clock3, ExternalLink, RefreshCcw, ShieldCheck, Star, WifiOff } from 'lucide-react';
import '../sunday-board.css';

type Game = {
  game_id: string; away_team: string; home_team: string;
  away_score: number|null; home_score: number|null; kickoff_utc: string|null;
  score_state: 'PUBLISHED_UNVERIFIED'|'NOT_PUBLISHED';
};
type Board = {
  authority: 'PUBLIC_SCHEDULE_NOT_LIVE_PBP'; season: number; week: number; games: Game[];
  source: {
    name: string; url: string; fetched_at_utc: string|null; age_seconds: number|null;
    stale: boolean; integrity_verified: boolean;
    refresh: {refreshed:boolean;throttled:boolean;error:string|null};
  };
  served_at_utc:string;
};
type Change = { key:string; game_id:string; team:string; text:string; at:string };
const RECHECK_MS = 300000;

function kickoff(iso:string|null) {
  if(!iso) return 'Time unavailable';
  const date=new Date(iso);
  return Number.isNaN(date.getTime())?'Unknown kickoff':date.toLocaleString(undefined,{weekday:'short',hour:'numeric',minute:'2-digit'});
}
function scoreLabel(g:Game) {
  if(g.score_state==='PUBLISHED_UNVERIFIED') return 'Published score · status unknown';
  if(!g.kickoff_utc) return 'Not reported';
  return Date.parse(g.kickoff_utc)>Date.now()?'Scheduled':'Result pending in public source';
}
function getFavorites():string[] {
  try { const x=JSON.parse(localStorage.getItem('pse_sunday_favorites')||'[]') as unknown; return Array.isArray(x)?x.filter((v):v is string=>typeof v==='string'):[]; }
  catch{return [];}
}

export function SundayBoard() {
  const [board,setBoard]=useState<Board|null>(null);
  const [error,setError]=useState<string|null>(null);
  const [busy,setBusy]=useState(false);
  const [favorites,setFavorites]=useState<string[]>(getFavorites);
  const [watchOnly,setWatchOnly]=useState(false);
  const [alerts,setAlerts]=useState(false);
  const [changes,setChanges]=useState<Change[]>([]);
  const [tick,setTick]=useState(0);
  const previous=useRef<Map<string,{a:number|null;h:number|null}>>(new Map());
  const ready=useRef(false);
  const pending=useRef<AbortController|null>(null);

  const load=useCallback(async (refresh:boolean)=>{
    pending.current?.abort();
    const controller=new AbortController();
    pending.current=controller;
    setBusy(true);
    try {
      const response=await fetch('/api/pse/v1/gameday/sunday-board?season=2026&refresh='+String(refresh),{signal:controller.signal});
      if(!response.ok)throw new Error('Source request failed (HTTP '+response.status+')');
      const next=await response.json() as Board;
      if(next.authority!=='PUBLIC_SCHEDULE_NOT_LIVE_PBP'||!Array.isArray(next.games))throw new Error('Unexpected data authority');
      if(controller.signal.aborted)return;
      if(ready.current){
        const found:Change[]=[];
        for(const g of next.games){
          const p=previous.current.get(g.game_id);
          if(!p||g.home_score==null||g.away_score==null)continue;
          if(p.a!==null&&p.a!==g.away_score)found.push({key:g.game_id+'a'+g.away_score+next.served_at_utc,game_id:g.game_id,team:g.away_team,text:'Published score: '+p.a+' to '+g.away_score+'. Play and timing unknown.',at:next.served_at_utc});
          if(p.h!==null&&p.h!==g.home_score)found.push({key:g.game_id+'h'+g.home_score+next.served_at_utc,game_id:g.game_id,team:g.home_team,text:'Published score: '+p.h+' to '+g.home_score+'. Play and timing unknown.',at:next.served_at_utc});
        }
        if(found.length)setChanges(old=>[...found,...old].slice(0,30));
      }
      previous.current=new Map(next.games.map(g=>[g.game_id,{a:g.away_score,h:g.home_score}]));
      ready.current=true;
      setBoard(next);
      setError(next.source.refresh.error);
      setTick(v=>v+1);
    }catch(e){
      if(!controller.signal.aborted)setError(e instanceof Error?e.message:'Unknown source error');
    }finally{if(!controller.signal.aborted)setBusy(false);}
  },[]);
  useEffect(()=>{
    void load(true);
    const id=window.setInterval(()=>void load(true),RECHECK_MS);
    return ()=>{window.clearInterval(id);pending.current?.abort();};
  },[load]);
  const toggle=(id:string)=>setFavorites(old=>{
    const next=old.includes(id)?old.filter(x=>x!==id):[...old,id];
    localStorage.setItem('pse_sunday_favorites',JSON.stringify(next));
    return next;
  });
  const games=(board?.games??[]).filter(g=>!watchOnly||favorites.includes(g.game_id))
    .sort((a,b)=>Number(favorites.includes(b.game_id))-Number(favorites.includes(a.game_id))||(a.kickoff_utc??'').localeCompare(b.kickoff_utc??''));
  const visibleChanges=changes.filter(c=>!watchOnly||favorites.includes(c.game_id));
  const age=board?.source.age_seconds;
  const freshness=age==null?'unknown age':Math.round(age/60)+' min old';
  const _tick=tick;
  void _tick;
  return <main className="sunday-root">
    <header className="sunday-head">
      <div><div className="sunday-kicker"><Activity size={15}/> FOURTH DOWN LAB / REDZONE COMPANION</div><h1>Every game. One command center.</h1>
      <p>A second-screen game board built on published source data, not a seconds-level play feed.</p></div>
      <div className="sunday-head-actions"><div className="sunday-source-status"><div className={'sunday-dot '+(board?.source.stale?'stale':'')}/><div><strong>{board?.source.stale?'STALE SOURCE':'PUBLIC SNAPSHOT'}</strong><small>{freshness}</small></div></div>
      <button onClick={()=>void load(true)} disabled={busy}><RefreshCcw size={16}/>{busy?'Updating…':'Refresh'}</button></div>
    </header>
    {error&&<div className="sunday-warning" role="status"><AlertTriangle size={17}/>{error}. {board?'Displaying the last good source snapshot.':'No game data available.'}</div>}
    <div className="sunday-stats">
      <div><Activity size={16}/><span>GAME WEEK</span><strong>{board?'2026 · '+board.week:'2026 · —'}</strong></div>
      <div><ShieldCheck size={16}/><span>GAMES LISTED</span><strong>{board?.games.length??'—'}</strong></div>
      <div><Clock3 size={16}/><span>PUBLIC POLLING</span><strong>5 minutes</strong></div>
      <div><WifiOff size={16}/><span>LIVE PBP / TRACKING</span><strong>Not connected</strong></div>
    </div>
    <div className="sunday-layout">
      <section className="sunday-primary">
        <div className="sunday-section-title"><div><h2>Game board</h2><p>Source-published scores can be delayed or corrected. Published scores do not establish whether a game is live or final.</p></div>
        <button onClick={()=>setWatchOnly(!watchOnly)} className={'sunday-filter '+(watchOnly?'active':'')} aria-pressed={watchOnly}>{watchOnly?'Watched games':'All games'}</button></div>
        {games.length?<div className="sunday-games">{games.map(g=><article className="sunday-game" key={g.game_id}>
          <div className="sunday-game-top"><span>{kickoff(g.kickoff_utc)}</span><button aria-pressed={favorites.includes(g.game_id)} aria-label={favorites.includes(g.game_id)?'Remove game from watchlist':'Watch game'} onClick={()=>toggle(g.game_id)}><Star size={17} fill={favorites.includes(g.game_id)?'#f5c975':'none'}/></button></div>
          <div className="sunday-score"><div><span>{g.away_team.slice(0,1)}</span><strong>{g.away_team}</strong><b>{g.away_score??'—'}</b></div><div><span>{g.home_team.slice(0,1)}</span><strong>{g.home_team}</strong><b>{g.home_score??'—'}</b></div></div>
          <div className="sunday-game-foot"><span>{scoreLabel(g)}</span><small>{g.game_id}</small></div>
        </article>)}</div>:<div className="sunday-empty">{!board?'Retrieving the public schedule source…':watchOnly?'Star your games to build a watch list.':'No games found in this week.'}</div>}
        <div className="sunday-trust"><ShieldCheck size={18}/><div><strong>Source truth, not cinematic guesswork</strong><p>We don't fabricate snap timing, possession, touchdowns, player routes, coaches' play calls, or player grades. The separate GameDay Lab houses synthetic teaching plays and authorized historical tracking imports.</p></div></div>
      </section>
      <aside className="sunday-side">
        <div className="sunday-panel"><div className="sunday-panel-title"><Bell size={17}/><h3>Score-change feed</h3></div><p>Updates are derived from differences between public snapshots, including possible corrections. No play types are inferred.</p>
          <label className="sunday-toggle"><input type="checkbox" checked={alerts} onChange={e=>setAlerts(e.target.checked)}/> Show in-page alerts</label>
          {alerts&&visibleChanges.length?<div className="sunday-events">{visibleChanges.map(e=><div className="sunday-event" key={e.key}><strong>{e.team} · Published score change</strong><p>{e.text}</p><small>{new Date(e.at).toLocaleTimeString()}</small></div>)}</div>:<div className="sunday-empty-small">{alerts?'No observed updates since loading the board.':'Alerts are currently off.'}</div>}
        </div>
        <div className="sunday-panel"><div className="sunday-panel-title"><ShieldCheck size={17}/><h3>Source health</h3></div>
          <div className="sunday-fact"><span>Provider</span><b>nflverse / Lee Sharpe</b></div>
          <div className="sunday-fact"><span>Source checksum</span><b>{board?.source.integrity_verified?'SHA-256 verified':'Not verified'}</b></div>
          <div className="sunday-fact"><span>Snapshot time</span><b>{board?.source.fetched_at_utc?new Date(board.source.fetched_at_utc).toLocaleTimeString():'Unavailable'}</b></div>
          <div className="sunday-fact"><span>Play-by-play</span><b>Not connected</b></div>
          <div className="sunday-fact"><span>3D tracking</span><b>Not connected</b></div>
          <a href="https://github.com/nflverse/nflverse-data/releases/tag/schedules" target="_blank" rel="noreferrer">Inspect published release <ExternalLink size={13}/></a>
        </div>
        <div className="sunday-panel"><div className="sunday-panel-title"><Activity size={17}/><h3>Next data layer</h3></div><p>Licensed live play-by-play will add actual clock, down, distance, possession and player-event alerts. Historical player tracking will enrich replays, but won't become real-time merely by being displayed in 3D.</p></div>
      </aside>
    </div>
    <footer className="sunday-footer">PUBLIC DELAYED SOURCE · NO LIVE PBP · NO TRACKING · <a href="?workspace=gameday">GameDay field lab</a></footer>
  </main>;
}
