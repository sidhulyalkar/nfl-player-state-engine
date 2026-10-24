import { useEffect, useMemo, useState, type ChangeEvent } from 'react';
import { Activity, Bell, ChevronRight, CircleAlert, Maximize2, Pause, Play, RotateCcw, Shield, SlidersHorizontal, Target, Zap } from 'lucide-react';
import '../gameday-lab.css';
import { HistoricalReplayPanel, parseHistoricalReplay, type HistoricalReplay } from './HistoricalReplayPanel';
import { FootballField3D, type Field3DTrail } from './FootballField3D';
import { MAX_REPLAY_FILE_BYTES, MAX_REPLAY_IMPORT_BYTES, MAX_REPLAY_LIBRARY, mergeReplayLibrary, replayKey, replayLabel, selectReplay } from './historicalReplayLibrary';
import { parsePlayCatalog, type PlayCatalog } from './historicalPlayCatalog';
import { HistoricalPlayCatalogPanel } from './HistoricalPlayCatalogPanel';
import {syntheticCameraCue} from './playCameraDirector';

/**
 * Illustrative data only. Production tracking adapters must carry a separate
 * source/rights contract and must never silently fall back to these coordinates.
 */
type Camera = 'broadcast' | 'all22' | 'overhead';
type Side = 'offense' | 'defense';
type PlayKind = 'pass' | 'run' | 'sack';
type Overlay = 'routes' | 'coverage' | 'labels';
interface Player {
  id: string;
  jersey: string;
  role: string;
  side: Side;
  x: number;
  y: number;
  dx: number;
  dy: number;
}
interface Moment { t: number; label: string; detail: string; type: 'snap' | 'throw' | 'result'; }
interface DemoPlay {
  id: string;
  down: string;
  title: string;
  kind: PlayKind;
  offense: string;
  defense: string;
  formation: string;
  defenseLook: string;
  interpretation: string;
  duration: number;
  ballCarrier: string;
  moments: Moment[];
}
const DURATION = 6.2;
const plays: DemoPlay[] = [
  {
    id: 'pass-demo', down: '2ND & 7', title: 'Crossing concept vs two-high shell',
    kind: 'pass', offense: 'ORBIT', defense: 'FORGE', formation: '11 personnel · shotgun trips',
    defenseLook: 'Two-high alignment · coverage unknown', duration: DURATION,
    ballCarrier: 'WR #11', interpretation: 'Illustration: the inside receiver crosses the middle while the outside receiver threatens vertically. Coverage and assignments are hypotheses, not observed coaching calls.',
    moments: [
      { t: .8, label: 'Snap', detail: 'Offense releases from 11 personnel', type: 'snap' },
      { t: 3.15, label: 'Pass released', detail: 'Illustrative throw toward the crossing receiver', type: 'throw' },
      { t: 4.35, label: 'Completion', detail: 'Example: 21-yard gain, first down', type: 'result' },
    ],
  },
  {
    id: 'run-demo', down: '1ST & 10', title: 'Inside-zone run and second-level fit',
    kind: 'run', offense: 'ORBIT', defense: 'FORGE', formation: '11 personnel · single back',
    defenseLook: 'Four-man front · run-fit responsibilities uncertain', duration: DURATION,
    ballCarrier: 'RB #22', interpretation: 'Illustration: the line works laterally and the back chooses a crease. Actual block success, missed tackles and assignments require film or licensed tracking.',
    moments: [
      { t: .8, label: 'Snap', detail: 'Running back attacks the line', type: 'snap' },
      { t: 2.25, label: 'Cutback', detail: 'Example: back redirects inside', type: 'throw' },
      { t: 4.35, label: 'Run finished', detail: 'Example: 9-yard gain', type: 'result' },
    ],
  },
  {
    id: 'sack-demo', down: '3RD & 8', title: 'Pressure vs six-man protection',
    kind: 'sack', offense: 'ORBIT', defense: 'FORGE', formation: '12 personnel · shotgun',
    defenseLook: 'Potential pressure · rush count illustrative', duration: DURATION,
    ballCarrier: 'QB #7', interpretation: 'Illustration: a rusher compresses the pocket. Responsibility cannot be attributed to a lineman, QB, receiver or coach without additional evidence.',
    moments: [
      { t: .8, label: 'Snap', detail: 'Example passing down begins', type: 'snap' },
      { t: 2.4, label: 'Pocket pressured', detail: 'Example: interior disruption', type: 'throw' },
      { t: 4.0, label: 'Sack', detail: 'Example: loss of 6 yards', type: 'result' },
    ],
  },
];
const DEMO_FOCUS = [-9,0,0] as const;
const roster: Player[] = [
  { id:'qb', jersey:'7', role:'QB', side:'offense', x:44,y:26.7,dx:-2,dy:0 },
  { id:'rb', jersey:'22', role:'RB', side:'offense', x:40,y:21,dx:7,dy:2 },
  { id:'wr1', jersey:'11', role:'WR', side:'offense', x:49,y:40,dx:24,dy:-13 },
  { id:'wr2', jersey:'18', role:'WR', side:'offense', x:49,y:48,dx:30,dy:-1 },
  { id:'wr3', jersey:'13', role:'WR', side:'offense', x:49,y:8,dx:21,dy:8 },
  { id:'te', jersey:'86', role:'TE', side:'offense', x:49,y:17,dx:10,dy:-2 },
  { id:'lt', jersey:'71', role:'LT', side:'offense', x:49,y:20,dx:0,dy:-2 },
  { id:'lg', jersey:'64', role:'LG', side:'offense', x:49,y:23,dx:0,dy:-1 },
  { id:'c', jersey:'61', role:'C', side:'offense', x:49,y:26.7,dx:0,dy:0 },
  { id:'rg', jersey:'66', role:'RG', side:'offense', x:49,y:30,dx:0,dy:1 },
  { id:'rt', jersey:'75', role:'RT', side:'offense', x:49,y:33,dx:0,dy:2 },
  { id:'de1', jersey:'91', role:'EDGE', side:'defense', x:53,y:19,dx:-7,dy:3 },
  { id:'dt1', jersey:'93', role:'DT', side:'defense', x:53,y:25,dx:-6,dy:0 },
  { id:'dt2', jersey:'95', role:'DT', side:'defense', x:53,y:30,dx:-6,dy:0 },
  { id:'de2', jersey:'98', role:'EDGE', side:'defense', x:53,y:36,dx:-7,dy:-3 },
  { id:'lb1', jersey:'54', role:'LB', side:'defense', x:58,y:19,dx:-4,dy:3 },
  { id:'lb2', jersey:'56', role:'LB', side:'defense', x:59,y:27,dx:-6,dy:0 },
  { id:'lb3', jersey:'51', role:'LB', side:'defense', x:58,y:36,dx:-4,dy:-2 },
  { id:'cb1', jersey:'24', role:'CB', side:'defense', x:57,y:8,dx:16,dy:8 },
  { id:'cb2', jersey:'29', role:'CB', side:'defense', x:57,y:47,dx:20,dy:-1 },
  { id:'fs', jersey:'31', role:'FS', side:'defense', x:71,y:22,dx:4,dy:1 },
  { id:'ss', jersey:'32', role:'SS', side:'defense', x:69,y:35,dx:4,dy:-7 },
];
function position(player: Player, t: number, kind: PlayKind) {
  const u = Math.min(1, Math.max(0, (t - .8) / 4.0));
  let dx = player.dx;
  let dy = player.dy;
  if (kind === 'run') {
    if (player.id === 'rb') { dx = 16; dy = 4; }
    if (player.id === 'qb') { dx = 0; dy = -2; }
    if (player.role === 'WR' || player.role === 'TE') { dx *= .25; dy *= .4; }
    if (player.side === 'defense') { dx *= .5; dy *= .65; }
  }
  if (kind === 'sack') {
    if (player.id === 'qb') { dx = -3; dy = 0; }
    if (player.id === 'rb') { dx = 2; dy = 1; }
    if (player.role === 'EDGE' || player.role === 'DT') { dx *= 1.2; }
    if (player.role === 'WR') { dx *= .5; }
  }
  return { x: player.x + dx * u, y: player.y + dy * u };
}
function project(x: number, y: number, z: number, camera: Camera) {
  const dx = x - 60;
  const dy = y - 26.65;
  if (camera === 'overhead') return { x: 520 + dx * 7.0, y: 292 + dy * 7.8 - z * 6 };
  if (camera === 'all22') return { x: 520 + dx * 6.1 + dy * 1.1, y: 288 + dy * 5.6 - dx * .8 - z * 7 };
  return { x: 520 + dx * 5.5 + dy * 2.2, y: 285 + dy * 4.1 - dx * 1.8 - z * 8 };
}
function polygon(vertices: Array<{x:number;y:number}>) {
  return vertices.map((v) => String(v.x.toFixed(1)) + ',' + String(v.y.toFixed(1))).join(' ');
}
function fieldQuad(x0: number, x1: number, camera: Camera) {
  return polygon([project(x0,0,0,camera),project(x1,0,0,camera),project(x1,53.3,0,camera),project(x0,53.3,0,camera)]);
}
function projectionPath(player: Player, kind: PlayKind, camera: Camera) {
  const values: string[] = [];
  for (let i=0; i<=24; i++) {
    const p = position(player,.8+4*i/24,kind);
    const at = project(p.x,p.y,.12,camera);
    values.push((i === 0 ? 'M' : 'L') + at.x.toFixed(1) + ' ' + at.y.toFixed(1));
  }
  return values.join(' ');
}
function Field({ play, time, camera, overlays, onPlayer }: {
  play: DemoPlay; time: number; camera: Camera; overlays: Set<Overlay>;
  onPlayer: (value: string) => void;
}) {
  const selectedCarrier = play.kind === 'run' ? 'rb' : play.kind === 'sack' ? 'qb' : 'wr1';
  const q = position(roster[0], Math.min(time,3.15),play.kind);
  const target = position(roster.find((p)=>p.id===selectedCarrier)!,Math.max(time,3.15),play.kind);
  const flying = play.kind === 'pass' && time > 3.15 && time < 4.35;
  const progress = Math.max(0, Math.min(1,(time - 3.15)/1.2));
  const ball = flying
    ? project(q.x+(target.x-q.x)*progress,q.y+(target.y-q.y)*progress,2+5*Math.sin(progress*Math.PI),camera)
    : null;
  return <svg className="gameday-field" viewBox="0 0 1040 590" role="img" aria-label="Illustrative three-dimensional projected football field with animated player positions">
    <defs>
      <linearGradient id="gameday-turf" x1="0" y1="0" x2=".7" y2="1"><stop offset="0%" stopColor="#20594a"/><stop offset="100%" stopColor="#102f2c"/></linearGradient>
      <filter id="gameday-glow"><feGaussianBlur stdDeviation="7"/></filter>
    </defs>
    <rect width="1040" height="590" fill="#0b1420"/>
    <ellipse cx="520" cy="310" rx="430" ry="165" fill="#317462" opacity=".10" filter="url(#gameday-glow)"/>
    <polygon points={fieldQuad(0,120,camera)} fill="url(#gameday-turf)" stroke="#b6d4c9" strokeWidth="2.4"/>
    {Array.from({length:24},(_,i)=>i*5).map((x)=> <polygon key={'stripe'+x} points={fieldQuad(x,x+5,camera)} fill={x%10===0?'#ffffff':'#00170e'} opacity=".025"/>)}
    <polygon points={fieldQuad(0,10,camera)} fill="#4acba9" opacity=".14"/>
    <polygon points={fieldQuad(110,120,camera)} fill="#ff9c6a" opacity=".13"/>
    {Array.from({length:21},(_,i)=>i*5+10).map((x)=>{
      const a=project(x,0,0,camera);const b=project(x,53.3,0,camera);
      return <g key={x}><line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="#dcefe8" opacity={x % 10 === 0 ? .36 : .14} strokeWidth={x % 10 === 0 ? 1.4 : .8}/></g>;
    })}
    {[10,20,30,40,50,60,70,80,90,100,110].map((x)=>{
      const p=project(x,26.65,0,camera);
      return <text key={'mark'+x} x={p.x} y={p.y} fill="#e4fff4" opacity=".20" fontSize="12" fontWeight="800" textAnchor="middle">{x<=60?x-10:110-x}</text>;
    })}
    {(()=>{const a=project(49,0,0,camera);const b=project(49,53.3,0,camera);return <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="#7eeac9" strokeWidth="3" strokeDasharray="7 5"/>;})()}
    {overlays.has('routes') && roster.filter((p)=>p.side==='offense' && ['WR','TE','RB'].includes(p.role)).map((p)=>
      <path key={'route'+p.id} d={projectionPath(p,play.kind,camera)} stroke={p.id===selectedCarrier?'#f6cb6b':'#98b6fb'} strokeWidth={p.id===selectedCarrier?3:1.7} fill="none" strokeDasharray="7 7" opacity={p.id === selectedCarrier ? .95 : .48}/>
    )}
    {overlays.has('coverage') && roster.filter((p)=>p.side==='defense').map((p)=>
      <path key={'coverage'+p.id} d={projectionPath(p,play.kind,camera)} stroke="#f48e8e" strokeWidth="1.5" opacity=".35" strokeDasharray="3 6" fill="none"/>
    )}
    {roster.map((p)=>{
      const at = position(p,time,play.kind);
      const shadow = project(at.x,at.y,0,camera);
      const dot = project(at.x,at.y,1.3,camera);
      const carrier = p.id===selectedCarrier;
      return <g key={p.id} tabIndex={0} role="button" aria-label={p.role+' number '+p.jersey} onClick={()=>onPlayer(p.id)} onKeyDown={(event)=>{if(event.key==='Enter')onPlayer(p.id);}} style={{cursor:'pointer'}}>
        <ellipse cx={shadow.x+3} cy={shadow.y+3} rx="10" ry="5" opacity=".45" fill="#031413"/>
        {carrier && <circle cx={dot.x} cy={dot.y} r="17" fill="none" stroke="#f8ce76" strokeWidth="1.5" opacity=".78"/>}
        <circle cx={dot.x} cy={dot.y} r="11.2" stroke="#eaf6ff" strokeWidth="1.5" fill={p.side==='offense'?'#4faef0':'#e97c7b'}/>
        <text x={dot.x} y={dot.y+3.7} textAnchor="middle" fill="#08192c" fontWeight="900" fontSize="9.7">{p.jersey}</text>
        {overlays.has('labels')&&<text x={dot.x} y={dot.y-17} textAnchor="middle" fill="#f1f5fc" fontSize="10" fontWeight="700">{p.role}</text>}
      </g>;
    })}
    {ball && <g><circle cx={ball.x} cy={ball.y} r="10" fill="#fbd77b" opacity=".25"/><circle cx={ball.x} cy={ball.y} r="4.5" fill="#ffdf99"/></g>}
    <text x="37" y="42" fill="#b8d1dc" fontSize="12" letterSpacing="2">FIELD LAB / ILLUSTRATIVE RECONSTRUCTION</text>
    <text x="37" y="64" fill="#72899a" fontSize="12">Spatial trajectories are not from an actual NFL game.</text>
  </svg>;
}
export function GameDayLab() {
  const [historical,setHistorical] = useState<HistoricalReplay|null>(null);
  const [replayLibrary,setReplayLibrary] = useState<HistoricalReplay[]>([]);
  const [importError,setImportError] = useState<string|null>(null);
  const [importing,setImporting] = useState(false);
  const [playCatalog,setPlayCatalog] = useState<PlayCatalog|null>(null);
  const [catalogError,setCatalogError] = useState<string|null>(null);
  async function onCatalogFile(event: ChangeEvent<HTMLInputElement>) {
    const file=event.target.files?.[0];
    event.target.value='';
    if(!file)return;
    try{
      if(file.size>2_000_000)throw new Error('A position-free source catalog must be under 2 MB.');
      const loaded=parsePlayCatalog(JSON.parse(await file.text()) as unknown);
      setPlayCatalog(loaded);
      setCatalogError(null);
    }catch(reason){
      setCatalogError(reason instanceof Error?reason.message:'Invalid source catalog JSON.');
    }
  }

  async function onReplayFile(event: ChangeEvent<HTMLInputElement>) {
    const files=Array.from(event.target.files??[]);
    event.target.value='';
    if(!files.length || importing) return;
    try {
      setImporting(true);
      if(files.length>MAX_REPLAY_LIBRARY)
        throw new Error('Choose at most '+MAX_REPLAY_LIBRARY+' research replay JSON files at a time.');
      if(files.some(file=>file.size>MAX_REPLAY_FILE_BYTES))
        throw new Error('Each historical replay JSON must be 25 MB or smaller.');
      if(files.reduce((sum,file)=>sum+file.size,0)>MAX_REPLAY_IMPORT_BYTES)
        throw new Error('A replay batch must be 50 MB or smaller.');
      const incoming:HistoricalReplay[]=[];
      for(const file of files){
        try {
          incoming.push(parseHistoricalReplay(JSON.parse(await file.text()) as unknown));
        } catch(reason) {
          const message=reason instanceof Error?reason.message:'Invalid replay format';
          throw new Error('File '+file.name+': '+message);
        }
      }
      // All-or-nothing: a conflicting play must not partially import a batch.
      const next=mergeReplayLibrary(replayLibrary,incoming);
      // Bound the total in-memory collection, not merely this upload batch.
      if(new TextEncoder().encode(JSON.stringify(next)).byteLength>MAX_REPLAY_IMPORT_BYTES)
        throw new Error('The in-memory research session is limited to 50 MB of replay JSON.');
      setReplayLibrary(next);
      setHistorical(selectReplay(next,replayKey(incoming[0])));
      setImportError(null);
      setPlaying(false);
    } catch(reason) {
      setImportError(reason instanceof Error?reason.message:'Invalid replay file');
    } finally {
      setImporting(false);
    }
  }
  const [index,setIndex] = useState(0);
  const [time,setTime] = useState(0);
  const [playing,setPlaying] = useState(true);
  const [speed,setSpeed] = useState(1);
  const [camera,setCamera] = useState<Camera>('broadcast');
  const [renderMode,setRenderMode] = useState<'3d'|'2d'>('3d');
  const [overlays,setOverlays] = useState<Set<Overlay>>(new Set(['routes','labels']));
  const [selected,setSelected] = useState('wr1');
  const [quiet,setQuiet] = useState(false);
  const [showRail,setShowRail] = useState(true);
  const play = plays[index];
  useEffect(()=>{
    if(!playing)return;
    let handle=0;
    let last=0;
    const tick=(now:number)=>{
      if(last>0)setTime(v=>Math.min(play.duration,v+(now-last)/1000*speed));
      last=now;
      handle=requestAnimationFrame(tick);
    };
    handle=requestAnimationFrame(tick);
    return ()=>cancelAnimationFrame(handle);
  },[playing,play.duration,speed,index]);
  useEffect(()=>{if(time>=play.duration&&playing)setPlaying(false);},[time,play.duration,playing]);
  const currentMoment=useMemo(()=>[...play.moments].reverse().find(e=>time>=e.t),[play,time]);
  const selectPlay=(i:number)=>{setIndex(i);setTime(0);setPlaying(true);setSelected(i===1?'rb':i===2?'qb':'wr1');};
  const toggle=(v:Overlay)=>setOverlays(old=>{const next=new Set(old);if(next.has(v))next.delete(v);else next.add(v);return next;});
  const focused=roster.find(p=>p.id===selected)!;
  const scenePlayers=useMemo(()=>roster.map(p=>({
    id:p.id,jersey:p.jersey,name:p.role,side:p.side,team:p.side,
    ...position(p,time,play.kind),
  })),[time,play.kind]);
  const sceneTrails=useMemo(()=>{
    const segments:Field3DTrail[]=[];
    for(let t=.8;t<Math.min(time,4.8);t+=.20){
      for(const p of roster){
        if(p.side==='offense'&&!overlays.has('routes'))continue;
        if(p.side==='defense'&&!overlays.has('coverage'))continue;
        const a=position(p,t,play.kind),b=position(p,Math.min(t+.20,time),play.kind);
        segments.push({id:p.id,from:[a.x,a.y],to:[b.x,b.y],side:p.side});
      }
    }
    return segments;
  },[time,play.kind,overlays]);
  const sceneBall=useMemo(()=>{
    if(play.kind!=='pass'){
      const p=roster.find(r=>r.id===(play.kind==='run'?'rb':'qb'))!;
      return position(p,time,play.kind);
    }
    const qb=roster[0],receiver=roster.find(r=>r.id==='wr1')!;
    if(time<=3.15)return position(qb,time,play.kind);
    const a=position(qb,3.15,play.kind),b=position(receiver,4.35,play.kind);
    const u=Math.max(0,Math.min(1,(time-3.15)/1.2));
    return {x:a.x+(b.x-a.x)*u,y:a.y+(b.y-a.y)*u};
  },[time,play.kind]);
  const demoCue=useMemo(()=>syntheticCameraCue(sceneBall,time<.8?'presnap':time<4.35?'live':'outcome'),[sceneBall,time]);
  return historical ? <HistoricalReplayPanel key={replayKey(historical)} replay={historical} library={replayLibrary} onSelect={key=>setHistorical(selectReplay(replayLibrary,key))} onImportFiles={onReplayFile} importing={importing} importError={importError} onBack={()=>{setHistorical(null);setTime(0);setPlaying(true);}}/> : <main className={'gameday-page gameday-theater '+(!showRail?'gameday-theater-expanded':'')}>
    <header className="gameday-head">
      <div><div className="gameday-kicker"><Activity size={15}/> FOURTH DOWN LAB / GAMEDAY</div><h1>See the game beneath the game.</h1><p>Replay the formation. Explore the decisions. Understand the contributions.</p></div>
      <div className="gameday-history-actions"><label className="gameday-history-upload">{importing?'Importing replay files…':'Load historical replay JSON(s)'}<input type="file" multiple disabled={importing} accept=".json,application/json" onChange={event=>{void onReplayFile(event);}}/></label><label className="gameday-history-upload">Load play catalog JSON<input type="file" accept=".json,application/json" onChange={event=>{void onCatalogFile(event);}}/></label>{replayLibrary.length>0&&<label className="gameday-library-picker">Loaded plays<select aria-label="Choose saved historical replay" value="" onChange={e=>setHistorical(selectReplay(replayLibrary,e.target.value))}><option value="" disabled>Select a play ({replayLibrary.length})</option>{replayLibrary.map(p=><option key={replayKey(p)} value={replayKey(p)}>{replayLabel(p)}</option>)}</select></label>}<div className="gameday-source"><span className="gameday-source-dot"/><div><strong>Synthetic demonstration</strong><small>Not a live game or licensed tracking feed</small></div></div></div>
    </header>
    {importError && <div className="gameday-import-error" role="alert">{importError}</div>}
    {catalogError && <div className="gameday-import-error" role="alert">{catalogError}</div>}
    {playCatalog&&<HistoricalPlayCatalogPanel catalog={playCatalog} library={replayLibrary}
      onOpen={setHistorical} onClose={()=>setPlayCatalog(null)}/>}
    <div className="gameday-layout">
      <section className="gameday-main">
        <div className="gameday-theater-topline"><span>ILLUSTRATIVE PLAY THEATER</span><button type="button" aria-pressed={showRail} onClick={()=>setShowRail(v=>!v)}>{showRail?'Expand field':'Show analysis rail'}</button></div>
        <div className="gameday-scoreline"><div><span className="gameday-team-mark">O</span><div><strong>{play.offense}</strong><small>OFFENSE</small></div><b>21</b></div><div className="gameday-situation"><span>DEMO PLAY</span><strong>{play.down}</strong><small>Q3 · 08:42 · ILLUSTRATIVE SCORE</small></div><div><b>17</b><div><strong>{play.defense}</strong><small>DEFENSE</small></div><span className="gameday-team-mark secondary">F</span></div></div>
        <div className="gameday-field-shell">
          <div className="gameday-toolbar"><strong><Maximize2 size={14}/> {renderMode==='3d'?'Interactive 3D stadium':'Projected 2D tactical field'}</strong><div className="gameday-display-options"><button aria-pressed={renderMode==='3d'} className={renderMode==='3d'?'selected':''} onClick={()=>setRenderMode('3d')}>3D Field</button><button aria-pressed={renderMode==='2d'} className={renderMode==='2d'?'selected':''} onClick={()=>setRenderMode('2d')}>2D Field</button><select aria-label="Camera angle" value={camera} onChange={e=>setCamera(e.target.value as Camera)}><option value="broadcast">Broadcast angle</option><option value="all22">All-22 perspective</option><option value="overhead">Overhead</option></select></div></div>
          {renderMode==='3d' ? <FootballField3D directorActive directorCue={demoCue} players={scenePlayers} ball={sceneBall} trails={sceneTrails} selectedId={selected} onSelect={setSelected} preset={camera} focus={DEMO_FOCUS} showTrails showLabels={overlays.has('labels')} showNearest={false} synthetic onUnsupported={()=>setRenderMode('2d')}/> : <Field play={play} time={time} camera={camera} overlays={overlays} onPlayer={setSelected}/> }
          {!quiet && currentMoment && <div className={'gameday-event-pill '+(currentMoment.type==='result'?'impact':'')}><Zap size={15}/><span><strong>{currentMoment.label}</strong> {currentMoment.detail}</span></div>}
        </div>
        <div className="gameday-controlbar"><div className="gameday-player-controls"><button aria-label={playing?'Pause replay':'Play replay'} onClick={()=>{if(time>=play.duration)setTime(0);setPlaying(!playing);}}>{playing?<Pause size={18}/>:<Play size={18}/>}</button><button aria-label="Restart replay" onClick={()=>{setTime(0);setPlaying(true);}}><RotateCcw size={17}/></button><span>{time.toFixed(1)}s / {play.duration.toFixed(1)}s</span></div><input aria-label="Replay timeline" type="range" min="0" max={play.duration} step=".05" value={time} onChange={e=>{setTime(Number(e.target.value));setPlaying(false);}}/><select aria-label="Playback speed" value={speed} onChange={e=>setSpeed(Number(e.target.value))}><option value=".5">0.5×</option><option value="1">1×</option><option value="2">2×</option></select></div>
        <div className="gameday-overlays"><span><SlidersHorizontal size={15}/> Tactical layers</span>{(['routes','coverage','labels'] as Overlay[]).map(o=><button key={o} className={overlays.has(o)?'enabled':''} onClick={()=>toggle(o)} aria-pressed={overlays.has(o)}>{o==='routes'?'Offensive routes':o==='coverage'?'Defensive movement':'Player labels'}</button>)}</div>
        <div className="gameday-lower">
          <div className="gameday-panel"><div className="gameday-section-name"><Target size={16}/> WHAT TO WATCH</div><h2>{play.title}</h2><p>{play.interpretation}</p><div className="gameday-evidence"><CircleAlert size={15}/> Scheme names are visual hypotheses unless verified through film/charting.</div></div>
          <div className="gameday-panel"><div className="gameday-section-name"><Shield size={16}/> FORMATION READ</div><div className="gameday-fact"><span>Offense</span><strong>{play.formation}</strong></div><div className="gameday-fact"><span>Defense</span><strong>{play.defenseLook}</strong></div><div className="gameday-fact"><span>Selected player</span><strong>{focused.role} #{focused.jersey} · {focused.side}</strong></div></div>
        </div>
      </section>
      {showRail&&<aside className="gameday-sidebar">
        <div className="gameday-panel gameday-feed"><div className="gameday-aside-heading"><div><Bell size={17}/><h2>Game events</h2></div><button aria-label="Toggle notifications" aria-pressed={!quiet} onClick={()=>setQuiet(!quiet)}>{quiet?'Muted':'Highlights on'}</button></div><p className="gameday-muted">Clickable replay moments. No external alerts are sent in demo mode.</p><div className="gameday-event-list">{[...play.moments].reverse().map((m,i)=><button key={i} className={time>=m.t?'seen':''} onClick={()=>{setTime(m.t);setPlaying(false);}}><span className="gameday-event-time">{m.t.toFixed(1)}s</span><div><strong>{m.label}</strong><small>{m.detail}</small></div><ChevronRight size={15}/></button>)}</div></div>
        <div className="gameday-panel"><div className="gameday-aside-heading"><div><Activity size={17}/><h2>Play library</h2></div></div><p className="gameday-muted">Three deterministic teaching scenarios.</p><div className="gameday-play-list">{plays.map((p,i)=><button key={p.id} className={i===index?'active':''} onClick={()=>selectPlay(i)}><span>0{i+1}</span><div><strong>{p.title}</strong><small>{p.down} · {p.kind.toUpperCase()}</small></div><ChevronRight size={15}/></button>)}</div></div>
        <div className="gameday-panel gameday-rating"><div className="gameday-aside-heading"><div><Shield size={17}/><h2>Player impact</h2></div></div><div className="gameday-grade-unavailable">— <span>/ 10</span></div><strong>No verified rating available</strong><p>Real grades will need position-specific opportunity, execution, uncertainty, and play-context evidence. Do not assign precise-looking numbers from the demo animation.</p><div className="gameday-rating-cats"><span>Decision quality</span><span>Execution</span><span>Value added</span><span>Teamwork</span></div></div>
      </aside>}
    </div>
    <footer className="gameday-footer">DEMO / NO LIVE SOURCE CONNECTED · AUTHORITY: SYNTHETIC_DEMO · No NFL game or player grade represented</footer>
  </main>;
}
