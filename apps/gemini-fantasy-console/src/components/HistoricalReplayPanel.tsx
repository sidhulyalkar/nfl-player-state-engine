import { useEffect, useMemo, useState, type ChangeEvent } from 'react';
import { Activity, ArrowLeft, CheckCircle2, ChevronLeft, ChevronRight, CircleAlert, Pause, Play, RotateCcw } from 'lucide-react';
import '../gameday-lab.css';
import { FootballField3D, type Field3DPlayer, type Field3DTrail } from './FootballField3D';
import { trackingFocus, sourceSnapIndex, observedTrailSegments } from './football3dMath';
import { motionAtFrame, buildObservedPathIndex, formationFootprint } from './trackingMotion';
import { displayClock, frameAtTime, stepFrame } from './trackingTimeline';

import { type HistoricalReplay } from './historicalReplaySchema';
import { replayKey, replayLabel } from './historicalReplayLibrary';
import {recordedNote,opponentProximitySeries,replayChapters} from './recordedCommentary';
import { recordedCameraCue } from './playCameraDirector';
export { parseHistoricalReplay } from './historicalReplaySchema';
export type { HistoricalReplay } from './historicalReplaySchema';
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
export function HistoricalReplayPanel({
  replay,library,onSelect,onImportFiles,importing,importError,onBack,
}: {
  replay:HistoricalReplay;
  library:readonly HistoricalReplay[];
  onSelect:(key:string)=>void;
  onImportFiles:(event:ChangeEvent<HTMLInputElement>)=>void;
  importing:boolean;
  importError:string|null;
  onBack:()=>void;
}) {
  const [time,setTime]=useState(0);
  const [running,setRunning]=useState(true);
  const [playbackSpeed,setPlaybackSpeed]=useState(1);
  const [camera,setCamera]=useState<Angle>('broadcast');
  const [renderMode,setRenderMode]=useState<'3d'|'2d'>('3d');
  const [trails,setTrails]=useState(true);
  const [labels,setLabels]=useState(true);
  const [showNearest,setShowNearest]=useState(true);
  const [showMotion,setShowMotion]=useState(true);
  const [showSnap,setShowSnap]=useState(true);
  const [focus,setFocus]=useState<string|null>(null);
  const [showRail,setShowRail]=useState(true);
  const [showCommentary,setShowCommentary]=useState(true);
  const duration=replay.frames[replay.frames.length-1].t_seconds_nominal;
  const snapFrame=useMemo(()=>{const i=sourceSnapIndex(replay.frames);return i<0?null:replay.frames[i];},[replay]);
  const snapPlayers=useMemo<Field3DPlayer[]>(()=>snapFrame?snapFrame.players.filter(p=>p.nfl_id).map(p=>({
    id:p.nfl_id!,x:p.x,y:p.y,jersey:p.jersey,name:p.name,team:p.team,
    side:p.side==='offense'||p.side==='defense'?p.side:null,
  })):[],[snapFrame]);
  const timeline=frameAtTime(replay.frames,time);
  const currentIndex=timeline.index;
  const sourceGap=timeline.is_gap;
  const frame=replay.frames[currentIndex];
  // Hold the most recently SOURCE-LABELED event's framing phase until another
  // labeled event arrives; never create a new event between recorded frames.
  const lastSourceEvent=useMemo(()=>{
    for(let i=currentIndex;i>=0;i--){
      if(replay.frames[i].events.length)return replay.frames[i].events;
    }
    return [] as string[];
  },[replay,currentIndex]);
  const directorCue=useMemo(()=>recordedCameraCue({...frame,events:lastSourceEvent},sourceGap,focus),
    [frame,lastSourceEvent,sourceGap,focus]);
  const measuredMotion=useMemo(()=>motionAtFrame(replay.frames,currentIndex),[replay,currentIndex]);
  const currentMotion=sourceGap?null:measuredMotion.find(p=>p.nfl_id===focus);
  const offenseNow=useMemo(()=>formationFootprint(frame.players,'offense'),[frame]);
  const defenseNow=useMemo(()=>formationFootprint(frame.players,'defense'),[frame]);
  const offenseAtSnap=useMemo(()=>snapFrame?formationFootprint(snapFrame.players,'offense'):null,[snapFrame]);
  const defenseAtSnap=useMemo(()=>snapFrame?formationFootprint(snapFrame.players,'defense'):null,[snapFrame]);
  const travelIndex=useMemo(()=>buildObservedPathIndex(replay.frames),[replay]);
  const traveled=focus?travelIndex.get(focus,currentIndex):null;
  const fieldFocus=useMemo(()=>trackingFocus(replay.frames[0].players),[replay]);
  const scenePlayers=useMemo<Field3DPlayer[]>(()=>frame.players.filter(p=>p.nfl_id).map(p=>({
    id:p.nfl_id!,x:p.x,y:p.y,jersey:p.jersey,name:p.name,team:p.team,
    side:p.side==='offense'||p.side==='defense'?p.side:null,
  })),[frame]);
  const sceneTrails=useMemo<Field3DTrail[]>(()=>observedTrailSegments(replay.frames,currentIndex),[currentIndex,replay]);
  const sceneMotion=useMemo(()=>measuredMotion.map(v=>({id:v.nfl_id,dx:v.dx,dy:v.dy,speed:v.computed_speed_yards_per_second})),[measuredMotion]);
  const chapters=useMemo(()=>replayChapters(replay),[replay]);
  useEffect(()=>{
    if(!running)return;
    let handle=0;let last=0;
    const step=(now:number)=>{if(last)setTime(v=>Math.min(duration,v+(now-last)/1000*playbackSpeed));last=now;handle=requestAnimationFrame(step);};
    handle=requestAnimationFrame(step);
    return ()=>cancelAnimationFrame(handle);
  },[running,duration,playbackSpeed]);
  useEffect(()=>{if(running&&time>=duration)setRunning(false);},[time,duration,running]);
  const focused=frame.players.find(p=>p.nfl_id===focus);
  const note=useMemo(()=>recordedNote(replay,currentIndex,sourceGap,focus),[replay,currentIndex,sourceGap,focus]);
  const proximity=useMemo(()=>opponentProximitySeries(replay,focus,currentIndex),[replay,focus,currentIndex]);
  const proximityMax=Math.max(5,proximity.max*1.12);
  const graphStart=replay.frames[0].t_seconds_nominal;
  const graphSpan=Math.max(.1,duration-graphStart);
  const chartX=(t:number)=>30+340*(t-graphStart)/graphSpan;
  const chartY=(yards:number)=>126-104*yards/proximityMax;
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
  return <main className={'gameday-page gameday-theater '+(!showRail?'gameday-theater-expanded':'')}>
    <header className="gameday-head">
      <div><div className="gameday-kicker"><Activity size={15}/> FOURTH DOWN LAB / HISTORICAL TRACKING</div><h1>Recorded movement, not reconstructed guesses.</h1><p>Game {replay.game_id} · play {replay.play_id} · recorded historical tracking</p></div>
      <div className="gameday-history-actions">
        <label className="gameday-library-picker">Research playlist
          <select aria-label="Select loaded historical play" value={replayKey(replay)} onChange={e=>onSelect(e.target.value)}>
            {library.map(p=><option key={replayKey(p)} value={replayKey(p)}>{replayLabel(p)}</option>)}
          </select>
        </label>
        <label className="gameday-history-upload">{importing?'Importing…':'Add replay JSON(s)'}
          <input type="file" multiple disabled={importing} accept=".json,application/json" onChange={onImportFiles}/>
        </label>
        <button onClick={onBack}><ArrowLeft size={15}/> Return to demo</button><div className="gameday-source"><span className="gameday-source-dot"/><div><strong>Historical research only</strong><small>Not live · rights not independently verified</small></div></div></div>
    </header>
    {importError&&<div className="gameday-import-error" role="alert">{importError}</div>}
    <div className="gameday-layout">
      <section className="gameday-main">
        <div className="gameday-theater-topline"><span>RECORDED FOOTBALL REPLAY · FRAME {frame.frame_id}</span><div><button type="button" aria-pressed={showCommentary} onClick={()=>setShowCommentary(v=>!v)}>{showCommentary?'Hide insights':'Show insights'}</button><button type="button" aria-pressed={showRail} onClick={()=>setShowRail(v=>!v)}>{showRail?'Expand field':'Show analysis rail'}</button></div></div>
        <div className="gameday-history-meta"><span><CheckCircle2 size={14}/> Recorded x/y coordinates</span><span>{replay.frame_count} frames</span><span>{replay.missing_frame_count} missing frames</span><span>Direction: {replay.play_direction ?? 'unknown'}</span></div>
        {replay.source_play_metadata&&<div className="gameday-charted-meta" aria-label="Source-declared play charting">
          <div><span>Game / possession</span><strong>{replay.source_play_metadata.visitor_team} @ {replay.source_play_metadata.home_team} · {replay.source_play_metadata.possession_team} ball</strong></div>
          <div><span>Source down / distance</span><strong>Q{replay.source_play_metadata.quarter} · {replay.source_play_metadata.down===null?'N/A':replay.source_play_metadata.down+' & '+(replay.source_play_metadata.yards_to_go===null?'?':replay.source_play_metadata.yards_to_go)}</strong></div>
          <div><span>Charted formation</span><strong>{replay.source_play_metadata.offense_formation_charted??'Unavailable'}</strong></div>
          <div><span>Charted personnel</span><strong>{replay.source_play_metadata.offense_personnel_charted??'Unavailable'}</strong></div>
          <small>Official play/game metadata as declared by the imported research file. The browser validates consistency, not the underlying CSV hash. No inferred play call or coverage.</small>
        </div>}
        <div className="gameday-field-shell">
          <div className="gameday-toolbar"><strong>Source positions only · no inferred coverage</strong><div className="gameday-display-options"><button aria-label="Use three dimensional recorded field" aria-pressed={renderMode==='3d'} className={renderMode==='3d'?'selected':''} onClick={()=>setRenderMode('3d')}>3D Field</button><button aria-label="Use two dimensional fallback field" aria-pressed={renderMode==='2d'} className={renderMode==='2d'?'selected':''} onClick={()=>setRenderMode('2d')}>2D Field</button><select aria-label="Historical replay camera" value={camera} onChange={e=>setCamera(e.target.value as Angle)}><option value="broadcast">Broadcast angle</option><option value="all22">All-22 perspective</option><option value="overhead">Overhead</option></select></div></div>
          {renderMode==='3d' ? <FootballField3D key={replay.game_id+':'+replay.play_id} directorActive={camera==='broadcast'} directorCue={directorCue} players={sourceGap?[]:scenePlayers} ball={!sourceGap&&frame.ball?{x:frame.ball.x,y:frame.ball.y}:null} trails={sceneTrails} selectedId={focus} onSelect={setFocus} preset={camera} focus={fieldFocus} showLabels={labels} showTrails={trails} showNearest={showNearest} showMotion={showMotion&&!sourceGap} motion={sourceGap?[]:sceneMotion} snapPlayers={snapPlayers} showSnap={showSnap} onUnsupported={()=>setRenderMode('2d')} /> : <svg className="gameday-field" viewBox="0 0 1040 590" role="img" aria-label="Recorded historical player tracking in a projected field">
            <rect width="1040" height="590" fill="#0b1420"/>
            <polygon points={quad(0,120,camera)} fill="#17473b" stroke="#a3d8ba" strokeWidth="2"/>
            <polygon points={quad(0,10,camera)} fill="#4ea9ac" opacity=".25"/>
            <polygon points={quad(110,120,camera)} fill="#4ea9ac" opacity=".25"/>
            {Array.from({length:21},(_,i)=>i*5+10).map(x=>{
              const a=point(x,0,camera),b=point(x,53.3,camera);
              return <line key={x} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="#d6f1e3" strokeWidth={x%10===0?1.5:.8} opacity=".3"/>;
            })}
            {showSnap && snapFrame && snapPlayers.map(p=>{const at=point(p.x,p.y,camera);return <circle key={'snap-'+p.id} cx={at.x} cy={at.y} r="10" fill="none" stroke="#d9e6e9" strokeDasharray="3 3" strokeWidth="1.7" opacity=".75"/>;})}
            {!sourceGap && showMotion && measuredMotion.map(v=>{
              const p=frame.players.find(e=>e.nfl_id===v.nfl_id);
              if(!p || v.displacement_yards<.005)return null;
              const scale=Math.min(3,Math.max(.8,v.computed_speed_yards_per_second*.24))/v.displacement_yards;
              const x=p.x+v.dx*scale,y=p.y+v.dy*scale;
              if(x<0||x>120||y<0||y>53.3)return null;
              const a=point(p.x,p.y,camera),b=point(x,y,camera);
              return <g key={'motion-'+v.nfl_id}><line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="#f9d98a" strokeWidth="2.3"/><circle cx={b.x} cy={b.y} r="2.8" fill="#f9d98a"/></g>;
            })}
            {trailSegments.map(l=><path key={l.key} d={l.path} stroke={l.color} strokeWidth="2.5" fill="none" opacity=".65"/>)}
            {showNearest && focusedPoint && nearestPoint && nearest && <g aria-label="Recorded nearest-opponent distance">
              <line x1={focusedPoint.x} y1={focusedPoint.y} x2={nearestPoint.x} y2={nearestPoint.y} stroke="#ffde94" strokeWidth="2.8" strokeDasharray="5 4"/>
              <circle cx={nearestPoint.x} cy={nearestPoint.y} r="17" fill="none" stroke="#ffde94" strokeWidth="2" opacity=".85"/>
              <g transform={'translate('+((focusedPoint.x+nearestPoint.x)/2)+','+((focusedPoint.y+nearestPoint.y)/2-10)+')'}>
                <rect x="-35" y="-13" width="70" height="23" rx="7" fill="#0b2530" stroke="#c8a979"/>
                <text x="0" y="2" fill="#ffe2a0" fontSize="11" fontWeight="800" textAnchor="middle">{nearest.distance.toFixed(1)} yd</text>
              </g>
            </g>}
            {!sourceGap&&frame.players.map((p,i)=>{
              const at=point(p.x,p.y,camera);
              const color=p.side==='offense'?'#57adf1':p.side==='defense'?'#f18f8f':'#b9c9d2';
              return <g key={p.nfl_id??'unknown-'+i} role="button" tabIndex={0} style={{cursor:'pointer'}} onClick={()=>setFocus(p.nfl_id)} onKeyDown={e=>{if(e.key==='Enter')setFocus(p.nfl_id);}}>
                <ellipse cx={at.x+2} cy={at.y+5} rx="11" ry="6" fill="#071f1f" opacity=".5"/>
                {focus&&focus===p.nfl_id&&<circle cx={at.x} cy={at.y} r="17" stroke="#f4cd79" fill="none" strokeWidth="2"/>}
                <circle cx={at.x} cy={at.y} r="11" stroke="#e8f5f7" strokeWidth="1.5" fill={color}/>
                {labels&&<text x={at.x} y={at.y+3.5} fill="#082030" fontSize="9" fontWeight="900" textAnchor="middle">{p.jersey??'•'}</text>}
              </g>;
            })}
            {!sourceGap&&frame.ball&&(()=>{const at=point(frame.ball.x,frame.ball.y,camera);return <circle cx={at.x} cy={at.y} r="5.3" fill="#ffd28c" stroke="#fff5dc" strokeWidth="1.5"/>;})()}
            <text x="33" y="45" fill="#e8f4f6" fontSize="12" letterSpacing="1.5">SOURCE FRAMES · {frame.frame_id}</text>
            <text x="33" y="65" fill="#a3bbbf" fontSize="11">Ball elevation unavailable; movement is NOT interpolated.</text>
          </svg>}
          {showCommentary&&<div className="gameday-director-commentary" role="status" aria-live="off"><span>ANALYST LENS · {note.provenance.replaceAll('_',' ')}{note.sourceFrameId!==null?' · FRAME '+note.sourceFrameId:''}</span><strong>{note.title}</strong><small>{note.detail}</small></div>}
          {sourceGap&&<div role="status" className="gameday-gap-banner">No position sample at {displayClock(time)} · last observed frame {frame.frame_id} · source frame unavailable</div>}
        </div>
        <div className="gameday-controlbar"><div className="gameday-player-controls">
          <button onClick={()=>{if(time>=duration)setTime(0);setRunning(!running);}} aria-label={running?'Pause replay':'Play replay'}>{running?<Pause size={18}/>:<Play size={18}/>}</button>
          <button onClick={()=>{setTime(0);setRunning(false);}} aria-label="Reset replay"><RotateCcw size={17}/></button>
          <button onClick={()=>{const next=stepFrame(replay.frames,currentIndex,-1);setTime(next.time);setRunning(false);}} aria-label="Previous recorded source frame" title="Previous observed frame"><ChevronLeft size={17}/></button>
          <button onClick={()=>{const next=stepFrame(replay.frames,currentIndex,1);setTime(next.time);setRunning(false);}} aria-label="Next recorded source frame" title="Next observed frame"><ChevronRight size={17}/></button>
          <span>{displayClock(time)} / {displayClock(duration)} · frame {frame.frame_id}{sourceGap?' (missing sample)':''}</span>
          <label className="gameday-playback-speed">Speed
            <select aria-label="Historical replay playback speed" value={playbackSpeed} onChange={e=>setPlaybackSpeed(Number(e.target.value))}>
              <option value={0.25}>0.25×</option><option value={0.5}>0.5×</option><option value={1}>1×</option><option value={2}>2×</option>
            </select>
          </label>
          </div><input type="range" aria-label="Historical replay timeline, recorded frames may contain gaps" min="0" max={duration} step=".01" value={time} onChange={e=>{setTime(Number(e.target.value));setRunning(false);}}/></div>
        {chapters.length>0&&<div className="gameday-replay-chapters" aria-label="Jump to source-annotated replay chapters"><span>EVENTS</span>{chapters.slice(0,24).map((chapter,i)=><button type="button" key={chapter.frameId+'-'+i} className={time>=chapter.time?'seen':''} onClick={()=>{setTime(chapter.time);setRunning(false);}} title={'Source event '+chapter.event+' at frame '+chapter.frameId}><small>{chapter.time.toFixed(1)}s</small>{chapter.title}</button>)}{chapters.length>24&&<small>{chapters.length-24} more annotated events</small>}</div>}
        <div className="gameday-overlays"><span>Recorded data layers</span><button onClick={()=>setTrails(!trails)} aria-pressed={trails} className={trails?'enabled':''}>Observed trails</button><button onClick={()=>setLabels(!labels)} aria-pressed={labels} className={labels?'enabled':''}>Jersey labels</button><button onClick={()=>setShowMotion(!showMotion)} aria-pressed={showMotion} className={showMotion?'enabled':''}>Observed movement</button>{snapFrame && <><button onClick={()=>setShowSnap(!showSnap)} aria-pressed={showSnap} className={showSnap?'enabled':''}>Snap alignment</button><button onClick={()=>{setTime(snapFrame.t_seconds_nominal);setRunning(false);}}>Jump to snap</button></>}<button onClick={()=>setShowNearest(!showNearest)} aria-pressed={showNearest} className={showNearest?'enabled':''}>Nearest opponent</button></div>
        <div className="gameday-lower">
          <div className="gameday-panel"><div className="gameday-section-name"><CircleAlert size={16}/> RESEARCH DATA BOUNDARY</div><h2>Not a live game feed</h2><p>Local contest frames are displayed without estimating formations, coverage, coaches' intent, player assignments, or ball height. Gaps in frames remain gaps.</p><div className="gameday-evidence">Data use requires independent source licensing and attribution review before any public product deployment.</div></div>
          <div className="gameday-panel"><div className="gameday-section-name">SELECTED OBSERVATION</div>
          <label className="gameday-observation-select-label">Inspect player
            <select className="gameday-observation-select" aria-label="Inspect tracked player" value={focus??''} onChange={e=>setFocus(e.target.value||null)}>
              <option value="">Select a tracked player</option>
              {frame.players.filter(p=>p.nfl_id).map(p=><option key={p.nfl_id} value={p.nfl_id!}>{p.name??p.nfl_id} {p.jersey?'#'+p.jersey:''} {p.team?'('+p.team+')':''}</option>)}
            </select>
          </label>{sourceGap&&<p className="gameday-muted">Position telemetry below belongs to last observed frame {frame.frame_id}, not the missing current sample.</p>}
          <div className="gameday-fact"><span>Entity</span><strong>{focused?.name??focused?.nfl_id??'Select a player'}</strong></div><div className="gameday-fact"><span>Team / side</span><strong>{focused?.team??'unavailable'} / {focused?.side??'unknown'}</strong></div><div className="gameday-fact"><span>Position</span><strong>{focused?focused.x.toFixed(2)+' x '+focused.y.toFixed(2)+' yd':'—'}</strong></div>
          <div className="gameday-fact"><span>Straight-line displacement from snap</span><strong>{straightFromSnap==null?'Unavailable':straightFromSnap.toFixed(2)+' yd'}</strong></div><div className="gameday-fact"><span>Source-reported speed</span><strong>{focused?.speed_yards_per_s==null?'Unavailable':focused.speed_yards_per_s.toFixed(2)+' yd/s'}</strong></div>
          <div className="gameday-fact"><span>Adjacent-frame speed</span><strong>{currentMotion?currentMotion.computed_speed_yards_per_second.toFixed(2)+' yd/s':'Insufficient consecutive frames'}</strong></div>
          <div className="gameday-fact"><span>Source-reported acceleration</span><strong>{focused?.acceleration_yards_per_s2==null?'Unavailable':focused.acceleration_yards_per_s2.toFixed(2)+' yd/s²'}</strong></div>
          <div className="gameday-fact"><span>Observed path length</span><strong>{traveled?traveled.yards.toFixed(2)+' yd'+(traveled.complete?'':' (partial)'):'Unavailable'}</strong></div>
          <div className="gameday-fact"><span>Nearest recorded opponent</span><strong>{nearest?nearest.distance.toFixed(2)+' yd':'Unavailable'}</strong></div>
          <div className="gameday-fact"><span>Opponent identity</span><strong>{nearest?(nearest.player.name??nearest.player.nfl_id??'Unknown'):'Unavailable'}</strong></div>
          {focus&&<div className="gameday-proximity-chart"><div className="gameday-proximity-head"><strong>Nearest-opponent distance over time</strong><span>{sourceGap?'GAP':proximity.latest?proximity.latest.distance.toFixed(1)+' yd':'unavailable'}</span></div><svg viewBox="0 0 400 150" role="img" aria-label="Recorded nearest-opponent separation in yards; disconnected lines mark evidence gaps"><line x1="30" x2="370" y1="126" y2="126" stroke="#536a78"/><line x1="30" x2="30" y1="12" y2="126" stroke="#536a78"/><text x="26" y="22" textAnchor="end" fill="#91b0bc" fontSize="11">{proximityMax.toFixed(0)}</text><text x="26" y="128" textAnchor="end" fill="#91b0bc" fontSize="11">0</text><text x="30" y="144" fill="#91b0bc" fontSize="10">Start</text><text x="370" y="144" textAnchor="end" fill="#91b0bc" fontSize="10">End</text>{proximity.paths.map((segment,i)=>segment.length>1?<path key={i} d={segment.map((v,j)=>(j?'L':'M')+chartX(v.time).toFixed(1)+' '+chartY(v.distance).toFixed(1)).join(' ')} fill="none" stroke="#75ddc4" strokeWidth="2"/>:<circle key={i} cx={chartX(segment[0].time)} cy={chartY(segment[0].distance)} r="2" fill="#75ddc4"/>)}{!sourceGap&&proximity.latest&&<circle cx={chartX(proximity.latest.time)} cy={chartY(proximity.latest.distance)} r="5" fill="#ffd18f" stroke="#202c33" strokeWidth="2"/>}</svg><small>Recorded opposite-side proximity, not defensive coverage. Lines break at missing frames, missing players, or missing side labels. {proximity.observed} valid observations.</small></div>}
          <p>Snap ghosts display only players recorded at the source-labeled snap event. Straight-line displacement is not total distance run. Movement arrows come from two adjacent recorded frames, not assumed orientation or coach assignment; source-reported and finite-difference speed are deliberately separate. Nearest opponent is geometric distance at a single recorded frame, not a coverage responsibility, matchup assignment, or player performance grade. Requires verified team possession labels.</p></div>
        </div>
      </section>
      {showRail&&<aside className="gameday-sidebar">
        <div className="gameday-panel">
          <div className="gameday-aside-heading"><div><Activity size={17}/><h2>Formation geometry</h2></div></div>
          <p className="gameday-muted">Measured team spacing. No coverage or play-call inference.</p>
          <div className="gameday-fact"><span>Offense at snap</span><strong>{offenseAtSnap?offenseAtSnap.count+' players · '+offenseAtSnap.width_yards.toFixed(1)+' yd wide':'No verified snap alignment'}</strong></div>
          <div className="gameday-fact"><span>Offense now</span><strong>{offenseNow?offenseNow.count+' players · '+offenseNow.width_yards.toFixed(1)+' yd wide':'Team labels unavailable'}</strong></div>
          <div className="gameday-fact"><span>Defense at snap</span><strong>{defenseAtSnap?defenseAtSnap.count+' players · '+defenseAtSnap.width_yards.toFixed(1)+' yd wide':'No verified snap alignment'}</strong></div>
          <div className="gameday-fact"><span>Defense now</span><strong>{defenseNow?defenseNow.count+' players · '+defenseNow.width_yards.toFixed(1)+' yd wide':'Team labels unavailable'}</strong></div>
          <div className="gameday-fact"><span>Offensive depth now</span><strong>{offenseNow?offenseNow.depth_yards.toFixed(1)+' yd':'Unavailable'}</strong></div>
          <p>Width is the measured sideline-to-sideline extent (max y minus min y); depth is max x minus min x. These depend on recorded players and independently verified team sides, not a named offensive formation.</p>
        </div>
        <div className="gameday-panel"><div className="gameday-aside-heading"><div><Activity size={17}/><h2>Replay notes</h2></div></div><p className="gameday-muted">The analyst lens follows source-labeled events as playback advances. Use the event chapter strip beneath the field to jump to a recorded moment.</p><div className="gameday-fact"><span>Source annotations</span><strong>{chapters.length}</strong></div><div className="gameday-fact"><span>Current evidence</span><strong>{note.provenance.replaceAll('_',' ')}</strong></div><p>Proximity and formation plots are geometric observations only. Coaching strategy, routes, coverage responsibilities and blocking outcomes require separate verified labels.</p></div>
        <div className="gameday-panel"><div className="gameday-aside-heading"><div><CircleAlert size={17}/><h2>Coverage and evidence</h2></div></div><div className="gameday-fact"><span>Frame coverage</span><strong>{(replay.frame_coverage*100).toFixed(1)}%</strong></div>{replay.position_quality&&<><div className="gameday-fact"><span>Unrenderable source positions</span><strong>{replay.position_quality.omitted_total_position_rows} excluded</strong></div>
        {replay.position_quality.omitted_total_position_rows>0&&<p role="status">Actual source rows omitted from the on-field view: {replay.position_quality.omitted_off_field_position_rows} outside the field; {replay.position_quality.omitted_missing_position_rows} missing x/y. Affected source frames: {replay.position_quality.affected_source_frame_ids.length}. These observations were not clamped or interpolated.</p>}</>}<div className="gameday-fact"><span>Source</span><strong>{replay.source}</strong></div><div className="gameday-fact"><span>License declaration</span><strong>{replay.source_license_identifier}</strong></div><div className="gameday-fact"><span>Game</span><strong>{replay.game_id}/{replay.play_id}</strong></div><p>Data are user supplied, not independently authenticated. No player grades or coaching classifications are generated.</p></div>
      </aside>}
    </div>
  </main>;
}
