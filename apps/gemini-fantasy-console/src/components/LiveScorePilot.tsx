import {useCallback,useEffect,useRef,useState} from 'react';
import {Activity,AlertTriangle,Clock3,RefreshCcw,ShieldCheck,Star,WifiOff} from 'lucide-react';

type State='pre'|'in'|'post';
export type LiveScoreGame={
  game_id:string;provider_event_id:string;home_team:string;away_team:string;
  home_score:number|null;away_score:number|null;kickoff_utc:string;
  state:State;period:number|null;clock:string|null;status_text:string|null;
  possession:null;down:null;distance:null;tracking_available:false;play_by_play_available:false;
};
export type LiveScoreBoard={
  schema_version:1;authority:'EXPERIMENTAL_UNLICENSED_SCOREBOARD_EVALUATION';
  data_mode:'EXPERIMENTAL_LIVE_SCORE_STATUS_ONLY';
  season:number;week:number;games:LiveScoreGame[];served_at_utc:string;
  source:{
    name:string;url:string;fetched_at_utc:string;age_seconds:number;
    stale:boolean;throttled:boolean;refresh_error:string|null;
    rights_status:string;official_api_contract:false;live_play_by_play:false;live_tracking:false;
  };
};
type Delta={key:string;gameId:string;heading:string;detail:string;at:string;kind:'score'|'state'};
const RECHECK_MS=30000;
const FUTURE_TIME_GUARD=120000;
export function liveScoreDeltas(before:LiveScoreBoard|null,after:LiveScoreBoard):Delta[]{
  if(!before||before.season!==after.season||before.week!==after.week||after.source.stale)return [];
  const prevT=Date.parse(before.source.fetched_at_utc),nextT=Date.parse(after.source.fetched_at_utc);
  if(!Number.isFinite(prevT)||!Number.isFinite(nextT)||nextT<=prevT)return [];
  const old=new Map(before.games.map(g=>[g.game_id,g]));
  const results:Delta[]=[];
  for(const game of after.games){
    const previous=old.get(game.game_id);
    if(!previous||previous.provider_event_id!==game.provider_event_id
      ||previous.home_team!==game.home_team||previous.away_team!==game.away_team)continue;
    const scoreChanged=(game.home_score!==previous.home_score||game.away_score!==previous.away_score)
      &&game.home_score!==null&&game.away_score!==null;
    if(scoreChanged)results.push({
      key:game.game_id+':score:'+nextT,gameId:game.game_id,kind:'score',
      heading:game.away_team+' at '+game.home_team+' · published score revision',
      detail:`${game.away_team} ${game.away_score} · ${game.home_team} ${game.home_score}. A score changed between source observations; scoring play, timing and player attribution are unknown.`,
      at:after.source.fetched_at_utc,
    });
    if(game.state!==previous.state)results.push({
      key:game.game_id+':state:'+nextT,gameId:game.game_id,kind:'state',
      heading:game.away_team+' at '+game.home_team+' · status update',
      detail:`Source state changed from ${previous.state} to ${game.state}. No game clock or possession is inferred between observations.`,
      at:after.source.fetched_at_utc,
    });
  }
  return results;
}
function getWatchlist():string[]{
  try{
    const value=JSON.parse(localStorage.getItem('pse_sunday_favorites')||'[]') as unknown;
    return Array.isArray(value)?value.filter((x):x is string=>typeof x==='string'):[];
  }catch{return [];}
}
function kickoff(value:string){
  const date=new Date(value);
  return Number.isFinite(date.getTime())?date.toLocaleString(undefined,{weekday:'short',hour:'numeric',minute:'2-digit'}):'Kickoff unavailable';
}
function sourceStatus(game:LiveScoreGame):string {
  if(game.state==='pre')return kickoff(game.kickoff_utc);
  if(game.state==='post')return 'Final · source reported';
  return `Q${game.period??'?'} · ${game.clock??'clock unavailable'} · source snapshot`;
}
function checkedBoard(value:unknown):LiveScoreBoard {
  if(!value||typeof value!=='object')throw new Error('Live response is not an object');
  const v=value as Partial<LiveScoreBoard>;
  if(v.authority!=='EXPERIMENTAL_UNLICENSED_SCOREBOARD_EVALUATION'
    ||v.data_mode!=='EXPERIMENTAL_LIVE_SCORE_STATUS_ONLY'
    ||!v.source||v.source.official_api_contract!==false||v.source.live_play_by_play!==false
    ||v.source.live_tracking!==false||!Number.isInteger(v.season)||!Number.isInteger(v.week)
    ||!Array.isArray(v.games)||v.games.length>24)throw new Error('Source authority mismatch');
  for(const g of v.games){
    if(!g||typeof g.game_id!=='string'||typeof g.provider_event_id!=='string'
      ||!['pre','in','post'].includes(g.state)
      ||!g.home_team||!g.away_team||g.play_by_play_available!==false
      ||g.tracking_available!==false||g.possession!==null||g.down!==null
      ||g.distance!==null||!Number.isFinite(Date.parse(g.kickoff_utc))
      ||(g.state==='in'&&(g.home_score===null||g.away_score===null)))
      throw new Error('Malformed score or unsupported play-by-play claim');
  }
  const fetched=Date.parse(v.source.fetched_at_utc);
  if(!Number.isFinite(fetched)||fetched>Date.now()+FUTURE_TIME_GUARD)throw new Error('Source timestamp invalid');
  return v as LiveScoreBoard;
}
export function LiveScorePilot(){
  const [board,setBoard]=useState<LiveScoreBoard|null>(null);
  const [error,setError]=useState<string|null>(null);
  const [busy,setBusy]=useState(false);
  const [filter,setFilter]=useState<'all'|'live'|'watched'>('all');
  const [favorites,setFavorites]=useState(getWatchlist);
  const [updates,setUpdates]=useState<Delta[]>([]);
  const [tick,setTick]=useState(0);
  const activeRequest=useRef<AbortController|null>(null);
  const previous=useRef<LiveScoreBoard|null>(null);
  const load=useCallback(async()=>{
    if(activeRequest.current)return;
    const abort=new AbortController();activeRequest.current=abort;setBusy(true);
    try{
      const res=await fetch('/api/pse/v1/gameday/experimental-live-scores?season=2026',
        {signal:abort.signal});
      if(!res.ok){
        if(res.status===403)throw new Error('Local pilot is disabled. Restart the repository root with PSE_EXPERIMENTAL_LIVE_SCORES=1 npm run dev:full after reviewing provider access terms.');
        throw new Error(`Experimental live-score source unavailable (HTTP ${res.status}). The delayed public board remains available.`);
      }
      const next=checkedBoard(await res.json() as unknown);
      if(abort.signal.aborted)return;
      const nextUpdates=liveScoreDeltas(previous.current,next);
      if(nextUpdates.length)setUpdates(old=>[...nextUpdates,...old].slice(0,50));
      previous.current=next;
      setBoard(next);
      setError(next.source.refresh_error);
    }catch(e){
      if(!abort.signal.aborted)setError(e instanceof Error?e.message:'Scoreboard request failed');
    }finally{
      if(activeRequest.current===abort){activeRequest.current=null;setBusy(false);}
    }
  },[]);
  useEffect(()=>{
    void load();
    const interval=setInterval(()=>void load(),RECHECK_MS);
    const ticker=setInterval(()=>setTick(i=>i+1),5000);
    return()=>{clearInterval(interval);clearInterval(ticker);activeRequest.current?.abort();};
  },[load]);
  const watch=(id:string)=>{
    setFavorites(prev=>{
      const updated=prev.includes(id)?prev.filter(item=>item!==id):[...prev,id];
      localStorage.setItem('pse_sunday_favorites',JSON.stringify(updated));return updated;
    });
  };
  const games=(board?.games??[]).filter(g=>filter==='all'||filter==='live'&&g.state==='in'||filter==='watched'&&favorites.includes(g.game_id))
    .sort((a,b)=>Number(b.state==='in')-Number(a.state==='in')
      ||Number(favorites.includes(b.game_id))-Number(favorites.includes(a.game_id))
      ||a.kickoff_utc.localeCompare(b.kickoff_utc));
  const selectedUpdates=updates.filter(u=>filter!=='watched'||favorites.includes(u.gameId));
  const age=board?Math.max(0,Math.round((Date.now()-Date.parse(board.source.fetched_at_utc))/1000)):null;
  const stale=Boolean(board?.source.stale||(age!==null&&age>=90));
  void tick;
  return <div className="sunday-live-root">
    <header className="sunday-live-head"><div>
      <div className="sunday-kicker"><Activity size={14}/> LOCAL LIVE-SCORE EVALUATION · UNOFFICIAL PROVIDER</div>
      <h1>Sunday, as reported.</h1>
      <p>Scores, game status and clock as last published by the provider. No game film, player tracking, possession, or verified scoring-play attribution.</p>
    </div><div className="sunday-live-tools"><span className={'sunday-live-health '+(stale?'stale':'')}>
      {board?(stale?'STALE SOURCE':board.games.some(g=>g.state==='in')?'GAMES IN PROGRESS':'SOURCE CONNECTED'):'NOT CONNECTED'} · {age===null?'age unknown':age+'s since fetch'}
      </span><button type="button" onClick={()=>void load()} disabled={busy}><RefreshCcw size={15}/>{busy?'Checking…':'Check now'}</button></div></header>
    {error&&<div className="sunday-warning" role="alert"><AlertTriangle size={16}/>{error}</div>}
    <div className="sunday-live-metrics">
      <div><strong>{board?.week??'—'}</strong><span>2026 NFL WEEK</span></div>
      <div><strong>{board?.games.filter(g=>g.state==='in').length??'—'}</strong><span>SOURCE-REPORTED LIVE</span></div>
      <div><strong>{board?.games.filter(g=>g.state==='post').length??'—'}</strong><span>FINAL</span></div>
      <div><strong>30s</strong><span>MINIMUM FETCH INTERVAL</span></div>
    </div>
    <div className="sunday-live-layout">
      <section className="sunday-live-primary">
        <div className="sunday-section-title"><div><h2>Game center</h2><p>Select live games, watch matchups, and compare status against the provider. Snapshots are not a continuous clock.</p></div>
        <div className="sunday-live-filters">{(['all','live','watched'] as const).map(f=><button type="button" key={f} className={filter===f?'active':''} aria-pressed={filter===f} onClick={()=>setFilter(f)}>{f==='all'?'All games':f==='live'?'In progress':'Watched'}</button>)}</div></div>
        <div className="sunday-live-games">{games.map(game=><article className={'sunday-live-game '+(game.state==='in'?'in-progress':'')} key={game.game_id}>
          <div className="sunday-live-game-top"><span className="sunday-live-game-state">{game.state==='in'?'IN PROGRESS':game.state==='post'?'FINAL':'UPCOMING'}</span><button type="button" aria-label={favorites.includes(game.game_id)?'Unwatch '+game.away_team+' at '+game.home_team:'Watch '+game.away_team+' at '+game.home_team} aria-pressed={favorites.includes(game.game_id)} onClick={()=>watch(game.game_id)}><Star size={15} fill={favorites.includes(game.game_id)?'#f3cd77':'none'}/></button></div>
          <div className="sunday-live-team"><span>{game.away_team}</span><strong>{game.away_score??'–'}</strong></div>
          <div className="sunday-live-team"><span>{game.home_team}</span><strong>{game.home_score??'–'}</strong></div>
          <div className="sunday-live-game-bottom"><Clock3 size={13}/>{sourceStatus(game)}</div>
          <small>Provider event {game.provider_event_id}</small>
        </article>)}</div>
        {!games.length&&<div className="sunday-empty">{!board?'Awaiting experimental provider response…':filter==='watched'?'Star a game to watch it here.':filter==='live'?'Provider reports no games currently in progress.':'No valid games returned.'}</div>}
        <div className="sunday-trust"><ShieldCheck size={16}/><div><strong>Local experiment, not licensed NFL production data</strong><p>Source: {board?.source.name??'ESPN Site API (unofficial)'}. Status and clock may lag or be corrected. Source responses are not themselves validated against live broadcast video. No play-by-play or tracking is inferred.</p></div></div>
      </section>
      <aside className="sunday-side">
        <div className="sunday-panel"><div className="sunday-panel-title"><Activity size={16}/><h3>Observed update feed</h3></div><p>Updates are differences between successful snapshots, not identified touchdown plays. The initial snapshot establishes a baseline.</p>
          {selectedUpdates.length?<div className="sunday-events" aria-live="off">{selectedUpdates.map(item=><div className="sunday-event" key={item.key}><strong>{item.heading}</strong><p>{item.detail}</p><small>Fetched {new Date(item.at).toLocaleTimeString()}</small></div>)}</div>:<div className="sunday-empty-small">No changes observed since opening this view. Leave it running during a game to test the next update.</div>}
        </div>
        <div className="sunday-panel"><div className="sunday-panel-title"><WifiOff size={16}/><h3>Source qualification</h3></div>
          <div className="sunday-fact"><span>Feed</span><b>Experimental ESPN scoreboard</b></div>
          <div className="sunday-fact"><span>Fetched</span><b>{board?new Date(board.source.fetched_at_utc).toLocaleTimeString():'Not yet'}</b></div>
          <div className="sunday-fact"><span>Freshness</span><b>{stale?'Stale / unavailable':'Recent snapshot'}</b></div>
          <div className="sunday-fact"><span>Play-by-play</span><b>Not connected</b></div>
          <div className="sunday-fact"><span>Player tracking</span><b>Not connected</b></div>
          <div className="sunday-fact"><span>Redistribution rights</span><b>Not established</b></div>
          <p>Requires explicit local opt-in. This unofficial endpoint can change or become unavailable without notice. Do not redistribute or use it as a production service without reviewing provider terms.</p>
        </div>
      </aside>
    </div>
  </div>;
}
