import {useEffect,useMemo,useState} from 'react';
import {ArrowLeft,ChevronLeft,ChevronRight,Pause,Play,RotateCcw} from 'lucide-react';
import type {HistoricalReplay,TrackedEntity} from './historicalReplaySchema';
import {replayKey,replayLabel} from './historicalReplayLibrary';
import {snapAlignedComparison,observedAtRelativeTime,compareObservedPlayer,
  comparisonUnavailableMessage} from './snapAlignedComparison';
import {displayClock} from './trackingTimeline';

const FIELD={left:43,top:23,width:714,height:315};
const fx=(x:number)=>FIELD.left+x/120*FIELD.width;
const fy=(y:number)=>FIELD.top+y/53.3*FIELD.height;
type Pane='left'|'right';

function RecordedOverhead({replay,seconds,selectedId,onSelect}:{
  replay:HistoricalReplay;seconds:number;selectedId:string|null;
  onSelect:(id:string|null)=>void;
}){
  const sample=observedAtRelativeTime(replay,seconds);
  const frame=sample.frame;
  return <div className="gameday-compare-field">
    <svg viewBox="0 0 800 370" role="img"
      aria-label={'Overhead field for game '+replay.game_id+' play '+replay.play_id+
        (frame?' recorded frame '+frame.frame_id:' source position unavailable')}>
      <rect width="800" height="370" rx="10" fill="#0c1c28"/>
      <rect x={FIELD.left} y={FIELD.top} width={FIELD.width} height={FIELD.height}
        fill="#214f43" stroke="#7caf9c" strokeWidth="2"/>
      {Array.from({length:13},(_,i)=>i*10).map(x=><g key={x}>
        <line x1={fx(x)} x2={fx(x)} y1={FIELD.top} y2={FIELD.top+FIELD.height}
          stroke="#d1f5e5" strokeOpacity=".33"/>
        <text x={fx(x)} y="354" fill="#b1d2d2" textAnchor="middle" fontSize="11">
          {x<=60?x:120-x}
        </text>
      </g>)}
      {frame?.players.map((p,i)=>{
        const selected=selectedId!=null&&selectedId===p.nfl_id;
        const color=p.side==='offense'?'#74bff5':p.side==='defense'?'#f2a09b':'#c0cad1';
        return <g key={p.nfl_id??'unidentified-'+i} role={p.nfl_id?'button':undefined}
          tabIndex={p.nfl_id?0:undefined}
          aria-label={p.nfl_id?'Select observed player '+p.nfl_id:undefined}
          onClick={()=>p.nfl_id&&onSelect(p.nfl_id)}
          onKeyDown={e=>{if(p.nfl_id&&(e.key==='Enter'||e.key===' ')){e.preventDefault();onSelect(p.nfl_id);}}}
          style={{cursor:p.nfl_id?'pointer':'default'}}>
          {selected&&<circle cx={fx(p.x)} cy={fy(p.y)} r="18" stroke="#ffe5a7" strokeWidth="3" fill="none"/>}
          <circle cx={fx(p.x)} cy={fy(p.y)} r="10" fill={color} stroke="#e9f5ef" strokeWidth="1.5"/>
          <text x={fx(p.x)} y={fy(p.y)+3} fontSize="8.5" fontWeight="800"
            textAnchor="middle" fill="#11202b">{p.jersey??'•'}</text>
        </g>;
      })}
      {frame?.ball&&<circle cx={fx(frame.ball.x)} cy={fy(frame.ball.y)} r="5" fill="#ffe4a3"/>}
      {!frame&&<g>
        <rect x="115" y="143" width="570" height="64" rx="9" fill="#0a202c" stroke="#e5a5a0"/>
        <text x="400" y="172" textAnchor="middle" fontWeight="700" fontSize="18" fill="#ffd2c7">NO RECORDED POSITION AT THIS TIME</text>
        <text x="400" y="194" textAnchor="middle" fill="#a9c5cb" fontSize="12">Skipped source frames are never interpolated.</text>
      </g>}
    </svg>
    <div className="gameday-compare-provenance">
      <span>{frame?'Recorded source frame '+frame.frame_id:'Missing recorded sample'}</span>
      <span>Nominal source time {displayClock(sample.nominal_seconds)}</span>
    </div>
  </div>;
}
function sourcePlayerOptions(replay:HistoricalReplay){
  const map=new Map<string,TrackedEntity>();
  for(const frame of replay.frames)
    for(const p of frame.players)if(p.nfl_id&&!map.has(p.nfl_id))map.set(p.nfl_id,p);
  return [...map.entries()].map(([id,p])=>({id,label:(p.name??id)+(p.jersey?' #'+p.jersey:'')}));
}
function ObservedStats({replay,time,selectedId}:{
  replay:HistoricalReplay;time:number;selectedId:string|null;
}){
  const stats=compareObservedPlayer(replay,time,selectedId);
  return <div className="gameday-compare-stats">
    <div className="gameday-fact"><span>Selected player</span><strong>{selectedId??'None'}</strong></div>
    <div className="gameday-fact"><span>Recorded frame</span><strong>{stats.frame_id??'Unavailable'}</strong></div>
    <div className="gameday-fact"><span>Straight-line distance from recorded snap</span>
      <strong>{stats.distance_from_snap_yards===null?'Unavailable':stats.distance_from_snap_yards.toFixed(2)+' yd'}</strong></div>
    <div className="gameday-fact"><span>Nearest recorded opponent</span>
      <strong>{stats.nearest_recorded_opponent_yards===null?'Unavailable':stats.nearest_recorded_opponent_yards.toFixed(2)+' yd'}</strong></div>
  </div>;
}

export function HistoricalPlayComparison({left,right,library,leftVerified,rightVerified,onLeft,onRight,onBack}:{
  left:HistoricalReplay;right:HistoricalReplay;library:readonly HistoricalReplay[];
  leftVerified:boolean;rightVerified:boolean;
  onLeft:(key:string)=>void;onRight:(key:string)=>void;onBack:()=>void;
}){
  const [relative,setRelative]=useState(0);
  const [playing,setPlaying]=useState(false);
  const [speed,setSpeed]=useState(1);
  const [selectedLeft,setSelectedLeft]=useState<string|null>(null);
  const [selectedRight,setSelectedRight]=useState<string|null>(null);
  const alignment=useMemo(()=>snapAlignedComparison(left,right),[left,right]);
  const optionsLeft=useMemo(()=>sourcePlayerOptions(left),[left]);
  const optionsRight=useMemo(()=>sourcePlayerOptions(right),[right]);
  const min=alignment.available?alignment.min_relative_seconds:0;
  const max=alignment.available?alignment.max_relative_seconds:0;
  const display=Math.min(max,Math.max(min,relative));
  useEffect(()=>{setRelative(0);setPlaying(false);setSelectedLeft(null);setSelectedRight(null);},[left,right]);
  useEffect(()=>{
    if(!playing||!alignment.available||max<=min)return;
    let frame=0,last=0;
    const tick=(now:number)=>{
      if(last>0)setRelative(value=>Math.min(max,value+(now-last)/1000*speed));
      last=now;
      frame=requestAnimationFrame(tick);
    };
    frame=requestAnimationFrame(tick);
    return ()=>cancelAnimationFrame(frame);
  },[playing,max,min,speed,alignment.available]);
  useEffect(()=>{if(playing&&relative>=max)setPlaying(false);},[relative,max,playing]);
  const valid=alignment.available;
  return <main className="gameday-page gameday-compare-page" aria-label="Two-play historical research comparison">
    <header className="gameday-head">
      <div>
        <div className="gameday-kicker">FOURTH DOWN LAB / OBSERVED PLAY COMPARISON</div>
        <h1>Compare recorded plays.</h1>
        <p>Two independent overhead fields. Shared clock only when both source files contain recorded snap events.</p>
      </div>
      <div className="gameday-history-actions"><button onClick={onBack}>
        <ArrowLeft size={15}/> Back to replay</button>
      </div>
    </header>
    <div className="gameday-timeline-notice" role="note">
      Research-only source files. Identical source hashes mean the declarations match,
      not that the browser independently authenticated original NFL CSVs.
      A snap-relative clock does not synchronize game film or establish tactical equivalence.
    </div>
    <div className="gameday-compare-selector">
      <label>Left recorded play
        <select aria-label="Left comparison play" value={replayKey(left)} onChange={e=>onLeft(e.target.value)}>
          {library.map(p=><option key={replayKey(p)} value={replayKey(p)}>{replayLabel(p)}</option>)}
        </select>
      </label>
      <label>Right recorded play
        <select aria-label="Right comparison play" value={replayKey(right)} onChange={e=>onRight(e.target.value)}>
          {library.map(p=><option key={replayKey(p)} value={replayKey(p)}>{replayLabel(p)}</option>)}
        </select>
      </label>
    </div>
    {!valid?<div className="gameday-import-error" role="alert">
      {comparisonUnavailableMessage(alignment.reason)}
      The view will not invent snap timing, copy trajectories, or compare different original tracking files.
    </div>:<>
      <div className="gameday-compare-controls">
        <div className="gameday-player-controls">
          <button aria-label={playing?'Pause comparison':'Play comparison'}
            onClick={()=>{if(display>=max)setRelative(min);setPlaying(!playing);}}>
            {playing?<Pause size={16}/>:<Play size={16}/>}</button>
          <button aria-label="Reset comparison to snap" onClick={()=>{setRelative(0);setPlaying(false);}}>
            <RotateCcw size={16}/></button>
          <button aria-label="Step comparison backward one nominal frame" onClick={()=>{setRelative(t=>Math.max(min,Math.round((t-.1)*10)/10));setPlaying(false);}}>
            <ChevronLeft size={16}/></button>
          <button aria-label="Step comparison forward one nominal frame" onClick={()=>{setRelative(t=>Math.min(max,Math.round((t+.1)*10)/10));setPlaying(false);}}>
            <ChevronRight size={16}/></button>
          <span>Snap-relative {display.toFixed(2)}s · common window {min.toFixed(2)} to {max.toFixed(2)}s</span>
          <label>Speed <select aria-label="Comparison playback speed" value={speed} onChange={e=>setSpeed(Number(e.target.value))}>
            <option value={0.25}>0.25×</option><option value={0.5}>0.5×</option><option value={1}>1×</option><option value={2}>2×</option>
          </select></label>
        </div>
        <input type="range" aria-label="Snap-relative comparison timeline"
          min={min} max={max} step={0.01} value={display}
          disabled={max<=min} onChange={e=>{setRelative(Number(e.target.value));setPlaying(false);}}/>
        <div className="gameday-compare-evidence">Snap frame IDs: left {alignment.left_snap_frame_id}, right {alignment.right_snap_frame_id}. Positions are recorded snapshots, not continuously tracked animation.</div>
      </div>
      <div className="gameday-compare-grid">
        {([
          {slot:'left' as Pane,replay:left,selected:selectedLeft,setSelected:setSelectedLeft,verified:leftVerified,options:optionsLeft},
          {slot:'right' as Pane,replay:right,selected:selectedRight,setSelected:setSelectedRight,verified:rightVerified,options:optionsRight},
        ]).map(p=><section key={p.slot} className="gameday-panel" aria-label={p.slot+' compared replay'}>
          <h2>Play {p.replay.play_id}</h2>
          <p className="gameday-muted">{p.replay.game_id} · {p.replay.frame_count} observed frames · {p.replay.missing_frame_count} missing frames</p>
          <p className="gameday-compare-integrity">{p.verified?'Local replay bytes match selected manifest':'Standalone: export file SHA-256 not verified'}</p>
          <RecordedOverhead replay={p.replay} seconds={display} selectedId={p.selected} onSelect={p.setSelected}/>
          <label className="gameday-compare-player">Inspect one recorded player
            <select aria-label={p.slot+' comparison player'} value={p.selected??''} onChange={e=>p.setSelected(e.target.value||null)}>
              <option value="">Choose player</option>
              {p.options.map(v=><option key={v.id} value={v.id}>{v.label}</option>)}
            </select>
          </label>
          <ObservedStats replay={p.replay} time={display} selectedId={p.selected}/>
        </section>)}
      </div>
      <p className="gameday-muted">No player matching across plays is assumed. Neither nearest-opponent separation nor straight-line displacement establishes coverage responsibility, successful execution, or causal player value. A blank field denotes an unrecorded sample, not zero movement.</p>
    </>}
  </main>;
}
