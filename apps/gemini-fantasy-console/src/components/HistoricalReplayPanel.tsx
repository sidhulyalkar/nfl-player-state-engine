import { useEffect, useMemo, useState } from 'react';
import { Activity, ArrowLeft, CheckCircle2, CircleAlert, Pause, Play, RotateCcw } from 'lucide-react';
import '../gameday-lab.css';
import { FootballField3D, type Field3DPlayer, type Field3DTrail } from './FootballField3D';
import { trackingFocus } from './football3dMath';

export interface TrackedEntity {
  nfl_id: string | null;
  is_ball: boolean;
  team: string | null;
  side: string | null;
  name: string | null;
  jersey: string | null;
  x: number;
  y: number;
  z: null;
  speed_yards_per_s: number | null;
}
export interface HistoricalFrame {
  frame_id: number;
  t_seconds_nominal: number;
  players: TrackedEntity[];
  ball: TrackedEntity | null;
  events: string[];
}
export interface HistoricalReplay {
  data_mode: 'HISTORICAL_RESEARCH';
  tracking_fidelity: 'RECORDED_FRAMES';
  game_id: string;
  play_id: string;
  source: string;
  source_file_sha256: string;
  source_license_identifier: string;
  play_direction: string | null;
  frame_count: number;
  missing_frame_count: number;
  frame_coverage: number;
  frames: HistoricalFrame[];
}
export function parseHistoricalReplay(value: unknown): HistoricalReplay {
  if (!value || typeof value !== 'object') throw new Error('Replay JSON must be an object.');
  const o = value as Partial<HistoricalReplay>;
  if (o.data_mode !== 'HISTORICAL_RESEARCH' || o.tracking_fidelity !== 'RECORDED_FRAMES') {
    throw new Error('Only research-labeled recorded tracking files can be imported.');
  }
  if (!Array.isArray(o.frames) || !o.frames.length || o.frames.length > 25000) {
    throw new Error('Replay must include 1 to 25,000 recorded frames.');
  }
  if (typeof o.game_id !== 'string' || typeof o.play_id !== 'string' || typeof o.source_file_sha256 !== 'string' || o.source_file_sha256.length !== 64) {
    throw new Error('Replay identity and source SHA-256 are required.');
  }
  if (o.frame_count !== o.frames.length) throw new Error('Recorded frame count does not match the payload.');
  for (let i=0;i<o.frames.length;i++) {
    const f = o.frames[i];
    if (!f || !Number.isInteger(f.frame_id) || !Number.isFinite(f.t_seconds_nominal) || f.t_seconds_nominal < 0 || !Array.isArray(f.players) || f.players.length > 30 || !Array.isArray(f.events)) {
      throw new Error('Invalid recorded frame structure.');
    }
    if (i>0 && (f.frame_id <= o.frames[i-1].frame_id || f.t_seconds_nominal < o.frames[i-1].t_seconds_nominal)) {
      throw new Error('Frames must have increasing source IDs and monotonic timestamps.');
    }
    for (const p of [...f.players,...(f.ball?[f.ball]:[])]) {
      if (!p || !Number.isFinite(p.x) || !Number.isFinite(p.y) || p.x<0 || p.x>120 || p.y<0 || p.y>53.3) {
        throw new Error('Tracked entity is missing field-space coordinates.');
      }
    }
  }
  return o as HistoricalReplay;
}
type Angle = 'broadcast' | 'all22' | 'overhead';
function point(x:number,y:number,camera:Angle){
  const a=x-60, b=y-26.65;
  if(camera==='overhead')return {x:520+a*7,y:295+b*7.8};
  if(camera==='all22')return {x:520+a*6.1+b*1.1,y:288+b*5.6-a*.8};
  return {x:520+a*5.5+b*2.2,y:285+b*4.1-a*1.8};
}
function quad(x0:number,x1:number,mode:Angle){
  return [point(x0,0,mode),point(x1,0,mode),point(x1,53.3,mode),point(x0,53.3,mode)]
    .map(p=>p.x.toFixed(1)+','+p.y.toFixed(1)).join(' ');
}
function activeFrame(frames:HistoricalFrame[],t:number){
  let lo=0, hi=frames.length-1;
  while(lo<hi){const mid=Math.ceil((lo+hi)/2);if(frames[mid].t_seconds_nominal<=t)lo=mid;else hi=mid-1;}
  return lo;
}
export function HistoricalReplayPanel({replay,onBack}: {replay:HistoricalReplay;onBack:()=>void}) {
  const [time,setTime]=useState(0);
  const [running,setRunning]=useState(true);
  const [camera,setCamera]=useState<Angle>('broadcast');
  const [renderMode,setRenderMode]=useState<'3d'|'2d'>('3d');
  const [trails,setTrails]=useState(true);
  const [labels,setLabels]=useState(true);
  const [showNearest,setShowNearest]=useState(true);
  const [showSnap,setShowSnap]=useState(true);
  const [focus,setFocus]=useState<string|null>(null);
  const duration=replay.frames[replay.frames.length-1].t_seconds_nominal;
  const snapFrame=useMemo(()=>replay.frames.find(f=>f.events.some(e=>['ball_snap','snap_direct','snap'].includes(e.toLowerCase())))??null,[replay]);
  const snapPlayers=useMemo<Field3DPlayer[]>(()=>snapFrame?snapFrame.players.filter(p=>p.nfl_id).map(p=>({
    id:p.nfl_id!,x:p.x,y:p.y,jersey:p.jersey,name:p.name,team:p.team,
    side:p.side==='offense'||p.side==='defense'?p.side:null,
  })):[],[snapFrame]);
  const currentIndex=activeFrame(replay.frames,time);
  const frame=replay.frames[currentIndex];
  const fieldFocus=useMemo(()=>trackingFocus(replay.frames[0].players),[replay]);
  const scenePlayers=useMemo<Field3DPlayer[]>(()=>frame.players.filter(p=>p.nfl_id).map(p=>({
    id:p.nfl_id!,x:p.x,y:p.y,jersey:p.jersey,name:p.name,team:p.team,
    side:p.side==='offense'||p.side==='defense'?p.side:null,
  })),[frame]);
  const sceneTrails=useMemo(()=>{
    const out:Field3DTrail[]=[];
    const startFrame=Math.max(1,currentIndex-30);
    for(let k=startFrame;k<=currentIndex;k++){
      const prior=replay.frames[k-1],next=replay.frames[k];
      if(!prior||next.frame_id!==prior.frame_id+1)continue;
      const index=new Map(prior.players.filter(p=>p.nfl_id).map(p=>[p.nfl_id!,p]));
      for(const p of next.players){
        const before=p.nfl_id?index.get(p.nfl_id):null;
        if(!before||!p.nfl_id)continue;
        out.push({id:p.nfl_id,from:[before.x,before.y],to:[p.x,p.y],side:p.side==='offense'||p.side==='defense'?p.side:null});
      }
    }
    return out;
  },[currentIndex,replay]);
  const recordedEvents=useMemo(()=>replay.frames.flatMap(f=>f.events.map(label=>({t:f.t_seconds_nominal,label,frame_id:f.frame_id}))),[replay]);
  useEffect(()=>{
    if(!running)return;
    let handle=0;let last=0;
    const step=(now:number)=>{if(last)setTime(v=>Math.min(duration,v+(now-last)/1000));last=now;handle=requestAnimationFrame(step);};
    handle=requestAnimationFrame(step);
    return ()=>cancelAnimationFrame(handle);
  },[running,duration]);
  useEffect(()=>{if(running&&time>=duration)setRunning(false);},[time,duration,running]);
  const focused=frame.players.find(p=>p.nfl_id===focus);
  const atSnap=focused&&snapFrame?snapFrame.players.find(p=>p.nfl_id===focused.nfl_id):null;
  const straightFromSnap=focused&&atSnap?Math.hypot(focused.x-atSnap.x,focused.y-atSnap.y):null;
  const nearest=focused && focused.side && (focused.side==='offense' || focused.side==='defense')
    ? frame.players.filter(p=>p.side && p.side!==focused.side)
      .map(p=>({player:p,distance:Math.hypot(p.x-focused.x,p.y-focused.y)}))
      .sort((a,b)=>a.distance-b.distance)[0]
    : undefined;
  const start=Math.max(0,currentIndex-30);
  const focusedPoint=focused?point(focused.x,focused.y,camera):null;
  const nearestPoint=nearest?point(nearest.player.x,nearest.player.y,camera):null;
  const trailSegments=useMemo(()=>{
    const result:Array<{key:string;path:string;color:string}>=[];
    if(!trails)return result;
    const ids=frame.players.map(p=>p.nfl_id).filter((v):v is string=>!!v);
    for(const id of ids){
      const player=frame.players.find(p=>p.nfl_id===id)!;
      let coords:string[]=[];
      let prev:number|null=null;
      for(let k=start;k<=currentIndex;k++){
        const f=replay.frames[k];
        const p=f.players.find(item=>item.nfl_id===id);
        if(!p){if(coords.length>1)result.push({key:id+'-'+k,path:coords.join(' '),color:player.side==='offense'?'#8ac7ef':'#f2a2a2'});coords=[];prev=null;continue;}
        const xy=point(p.x,p.y,camera);
        const command=(prev===null || f.frame_id!==prev+1?'M':'L')+xy.x.toFixed(1)+' '+xy.y.toFixed(1);
        coords.push(command);prev=f.frame_id;
      }
      if(coords.length>1)result.push({key:id+'-final',path:coords.join(' '),color:player.side==='offense'?'#8ac7ef':'#f2a2a2'});
    }
    return result;
  },[frame,replay,start,currentIndex,trails,camera]);
  return <main className="gameday-page">
    <header className="gameday-head">
      <div><div className="gameday-kicker"><Activity size={15}/> FOURTH DOWN LAB / HISTORICAL TRACKING</div><h1>Recorded movement, not reconstructed guesses.</h1><p>Game {replay.game_id} · play {replay.play_id} · recorded historical tracking</p></div>
      <div className="gameday-history-actions"><button onClick={onBack}><ArrowLeft size={15}/> Return to demo</button><div className="gameday-source"><span className="gameday-source-dot"/><div><strong>Historical research only</strong><small>Not live · rights not independently verified</small></div></div></div>
    </header>
    <div className="gameday-layout">
      <section className="gameday-main">
        <div className="gameday-history-meta"><span><CheckCircle2 size={14}/> Recorded x/y coordinates</span><span>{replay.frame_count} frames</span><span>{replay.missing_frame_count} missing frames</span><span>Direction: {replay.play_direction ?? 'unknown'}</span></div>
        <div className="gameday-field-shell">
          <div className="gameday-toolbar"><strong>Source positions only · no inferred coverage</strong><div className="gameday-display-options"><button aria-label="Use three dimensional recorded field" aria-pressed={renderMode==='3d'} className={renderMode==='3d'?'selected':''} onClick={()=>setRenderMode('3d')}>3D Field</button><button aria-label="Use two dimensional fallback field" aria-pressed={renderMode==='2d'} className={renderMode==='2d'?'selected':''} onClick={()=>setRenderMode('2d')}>2D Field</button><select aria-label="Historical replay camera" value={camera} onChange={e=>setCamera(e.target.value as Angle)}><option value="broadcast">Broadcast angle</option><option value="all22">All-22 perspective</option><option value="overhead">Overhead</option></select></div></div>
          {renderMode==='3d' ? <FootballField3D key={replay.game_id+':'+replay.play_id} players={scenePlayers} ball={frame.ball?{x:frame.ball.x,y:frame.ball.y}:null} trails={sceneTrails} selectedId={focus} onSelect={setFocus} preset={camera} focus={fieldFocus} showLabels={labels} showTrails={trails} showNearest={showNearest} snapPlayers={snapPlayers} showSnap={showSnap} onUnsupported={()=>setRenderMode('2d')} /> : <svg className="gameday-field" viewBox="0 0 1040 590" role="img" aria-label="Recorded historical player tracking in a projected field">
            <rect width="1040" height="590" fill="#0b1420"/>
            <polygon points={quad(0,120,camera)} fill="#17473b" stroke="#a3d8ba" strokeWidth="2"/>
            <polygon points={quad(0,10,camera)} fill="#4ea9ac" opacity=".25"/>
            <polygon points={quad(110,120,camera)} fill="#4ea9ac" opacity=".25"/>
            {Array.from({length:21},(_,i)=>i*5+10).map(x=>{
              const a=point(x,0,camera),b=point(x,53.3,camera);
              return <line key={x} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="#d6f1e3" strokeWidth={x%10===0?1.5:.8} opacity=".3"/>;
            })}
            {showSnap && snapFrame && snapPlayers.map(p=>{const at=point(p.x,p.y,camera);return <circle key={'snap-'+p.id} cx={at.x} cy={at.y} r="10" fill="none" stroke="#d9e6e9" strokeDasharray="3 3" strokeWidth="1.7" opacity=".75"/>;})}
            {trailSegments.map(l=><path key={l.key} d={l.path} stroke={l.color} strokeWidth="2.5" fill="none" opacity=".65"/>)}
            {showNearest && focusedPoint && nearestPoint && nearest && <g aria-label="Recorded nearest-opponent distance">
              <line x1={focusedPoint.x} y1={focusedPoint.y} x2={nearestPoint.x} y2={nearestPoint.y} stroke="#ffde94" strokeWidth="2.8" strokeDasharray="5 4"/>
              <circle cx={nearestPoint.x} cy={nearestPoint.y} r="17" fill="none" stroke="#ffde94" strokeWidth="2" opacity=".85"/>
              <g transform={'translate('+((focusedPoint.x+nearestPoint.x)/2)+','+((focusedPoint.y+nearestPoint.y)/2-10)+')'}>
                <rect x="-35" y="-13" width="70" height="23" rx="7" fill="#0b2530" stroke="#c8a979"/>
                <text x="0" y="2" fill="#ffe2a0" fontSize="11" fontWeight="800" textAnchor="middle">{nearest.distance.toFixed(1)} yd</text>
              </g>
            </g>}
            {frame.players.map((p,i)=>{
              const at=point(p.x,p.y,camera);
              const color=p.side==='offense'?'#57adf1':p.side==='defense'?'#f18f8f':'#b9c9d2';
              return <g key={p.nfl_id??'unknown-'+i} role="button" tabIndex={0} style={{cursor:'pointer'}} onClick={()=>setFocus(p.nfl_id)} onKeyDown={e=>{if(e.key==='Enter')setFocus(p.nfl_id);}}>
                <ellipse cx={at.x+2} cy={at.y+5} rx="11" ry="6" fill="#071f1f" opacity=".5"/>
                {focus&&focus===p.nfl_id&&<circle cx={at.x} cy={at.y} r="17" stroke="#f4cd79" fill="none" strokeWidth="2"/>}
                <circle cx={at.x} cy={at.y} r="11" stroke="#e8f5f7" strokeWidth="1.5" fill={color}/>
                {labels&&<text x={at.x} y={at.y+3.5} fill="#082030" fontSize="9" fontWeight="900" textAnchor="middle">{p.jersey??'•'}</text>}
              </g>;
            })}
            {frame.ball&&(()=>{const at=point(frame.ball.x,frame.ball.y,camera);return <circle cx={at.x} cy={at.y} r="5.3" fill="#ffd28c" stroke="#fff5dc" strokeWidth="1.5"/>;})()}
            <text x="33" y="45" fill="#e8f4f6" fontSize="12" letterSpacing="1.5">SOURCE FRAMES · {frame.frame_id}</text>
            <text x="33" y="65" fill="#a3bbbf" fontSize="11">Ball elevation unavailable; movement is NOT interpolated.</text>
          </svg>}
        </div>
        <div className="gameday-controlbar"><div className="gameday-player-controls"><button onClick={()=>{if(time>=duration)setTime(0);setRunning(!running);}} aria-label={running?'Pause':'Play'}>{running?<Pause size={18}/>:<Play size={18}/>}</button><button onClick={()=>{setTime(0);setRunning(true);}} aria-label="Restart"><RotateCcw size={17}/></button><span>{time.toFixed(1)} / {duration.toFixed(1)}s</span></div><input type="range" aria-label="Historical frame scrubber" min="0" max={duration} step=".1" value={time} onChange={e=>{setTime(Number(e.target.value));setRunning(false);}}/></div>
        <div className="gameday-overlays"><span>Recorded data layers</span><button onClick={()=>setTrails(!trails)} aria-pressed={trails} className={trails?'enabled':''}>Observed trails</button><button onClick={()=>setLabels(!labels)} aria-pressed={labels} className={labels?'enabled':''}>Jersey labels</button>{snapFrame && <><button onClick={()=>setShowSnap(!showSnap)} aria-pressed={showSnap} className={showSnap?'enabled':''}>Snap alignment</button><button onClick={()=>{setTime(snapFrame.t_seconds_nominal);setRunning(false);}}>Jump to snap</button></>}<button onClick={()=>setShowNearest(!showNearest)} aria-pressed={showNearest} className={showNearest?'enabled':''}>Nearest opponent</button></div>
        <div className="gameday-lower">
          <div className="gameday-panel"><div className="gameday-section-name"><CircleAlert size={16}/> RESEARCH DATA BOUNDARY</div><h2>Not a live game feed</h2><p>Local contest frames are displayed without estimating formations, coverage, coaches' intent, player assignments, or ball height. Gaps in frames remain gaps.</p><div className="gameday-evidence">Data use requires independent source licensing and attribution review before any public product deployment.</div></div>
          <div className="gameday-panel"><div className="gameday-section-name">SELECTED OBSERVATION</div>
          <label className="gameday-observation-select-label">Inspect player
            <select className="gameday-observation-select" aria-label="Inspect tracked player" value={focus??''} onChange={e=>setFocus(e.target.value||null)}>
              <option value="">Select a tracked player</option>
              {frame.players.filter(p=>p.nfl_id).map(p=><option key={p.nfl_id} value={p.nfl_id!}>{p.name??p.nfl_id} {p.jersey?'#'+p.jersey:''} {p.team?'('+p.team+')':''}</option>)}
            </select>
          </label><div className="gameday-fact"><span>Entity</span><strong>{focused?.name??focused?.nfl_id??'Select a player'}</strong></div><div className="gameday-fact"><span>Team / side</span><strong>{focused?.team??'unavailable'} / {focused?.side??'unknown'}</strong></div><div className="gameday-fact"><span>Position</span><strong>{focused?focused.x.toFixed(2)+' x '+focused.y.toFixed(2)+' yd':'—'}</strong></div><div className="gameday-fact"><span>Speed</span><strong>{focused?.speed_yards_per_s==null?'unavailable':focused.speed_yards_per_s.toFixed(1)+' yd/s'}</strong></div>
          <div className="gameday-fact"><span>Straight-line displacement from snap</span><strong>{straightFromSnap==null?'Unavailable':straightFromSnap.toFixed(2)+' yd'}</strong></div><div className="gameday-fact"><span>Nearest recorded opponent</span><strong>{nearest?nearest.distance.toFixed(2)+' yd':'Unavailable'}</strong></div>
          <div className="gameday-fact"><span>Opponent identity</span><strong>{nearest?(nearest.player.name??nearest.player.nfl_id??'Unknown'):'Unavailable'}</strong></div>
          <p>Snap ghosts display only players recorded at the source-labeled snap event. Straight-line displacement is not total distance run. Nearest opponent is geometric distance at a single recorded frame, not a coverage responsibility, matchup assignment, or player performance grade. Requires verified team possession labels.</p></div>
        </div>
      </section>
      <aside className="gameday-sidebar">
        <div className="gameday-panel"><div className="gameday-aside-heading"><div><Activity size={17}/><h2>Source events</h2></div></div><p className="gameday-muted">Only labels supplied by the original tracking CSV.</p><div className="gameday-event-list">{recordedEvents.length?recordedEvents.slice(0,50).map((m,i)=><button key={i} className={time>=m.t?'seen':''} onClick={()=>{setTime(m.t);setRunning(false);}}><span className="gameday-event-time">{m.t.toFixed(1)}s</span><div><strong>{m.label}</strong><small>Recorded frame {m.frame_id}</small></div></button>):<p>No annotated events available.</p>}</div></div>
        <div className="gameday-panel"><div className="gameday-aside-heading"><div><CircleAlert size={17}/><h2>Coverage and evidence</h2></div></div><div className="gameday-fact"><span>Frame coverage</span><strong>{(replay.frame_coverage*100).toFixed(1)}%</strong></div><div className="gameday-fact"><span>Source</span><strong>{replay.source}</strong></div><div className="gameday-fact"><span>License declaration</span><strong>{replay.source_license_identifier}</strong></div><div className="gameday-fact"><span>Game</span><strong>{replay.game_id}/{replay.play_id}</strong></div><p>Data are user supplied, not independently authenticated. No player grades or coaching classifications are generated.</p></div>
      </aside>
    </div>
  </main>;
}
