/** Evidence-bounded commentary emitted at replay PLAYBACK time, not live NFL time.
 * Only explicitly source-labeled events and measured frame geometry are used.
 */
import type { HistoricalReplay, HistoricalFrame, TrackedEntity } from './historicalReplaySchema';

export interface RecordedNote {
  title:string;
  detail:string;
  provenance:'SOURCE_EVENT'|'OBSERVED_GEOMETRY'|'EVIDENCE_GAP';
  sourceFrameId:number|null;
  sourceTimeSeconds:number|null;
  rawEvent:string|null;
}
type SeenEvent={event:string;frame:HistoricalFrame};
function latestEvent(frames:readonly HistoricalFrame[],current:number):SeenEvent|null {
  for(let i=current;i>=0;i--){
    const f=frames[i];
    const e=f.events.find(value=>value.trim().length>0);
    if(e)return {event:e,frame:f};
  }
  return null;
}
function titleForEvent(source:string):string {
  const e=source.toLowerCase();
  // These are source tags, not predictions or video-confirmed classifications.
  if(['ball_snap','snap_direct','snap'].includes(e))return 'Snap recorded';
  if(e.includes('pass_forward'))return 'Forward pass released';
  if(e.includes('pass_arrived'))return 'Pass arrival annotated';
  if(e.includes('pass_outcome_caught'))return 'Catch outcome annotated';
  if(e.includes('pass_outcome_incomplete'))return 'Incomplete pass annotated';
  if(e.includes('handoff'))return 'Handoff annotated';
  if(e.includes('tackle'))return 'Tackle event annotated';
  if(e.includes('touchdown'))return 'Touchdown event annotated';
  if(e.includes('out_of_bounds'))return 'Out-of-bounds event annotated';
  return 'Source event recorded';
}
function label(source:string):string {
  return source.replaceAll('_',' ').slice(0,96);
}
function isValid(p:TrackedEntity):boolean {
  return Number.isFinite(p.x)&&Number.isFinite(p.y)&&p.x>=0&&p.x<=120&&p.y>=0&&p.y<=53.3;
}
export function observedNearestOpponent(frame:HistoricalFrame,selectedId:string|null):
  {distance:number;name:string;playerId:string}|null {
  if(!selectedId)return null;
  const selected=frame.players.find(p=>p.nfl_id===selectedId);
  if(!selected||!isValid(selected)||!['offense','defense'].includes(selected.side??''))return null;
  const opponents=frame.players.filter(p=>p.side&&p.side!==selected.side
    &&['offense','defense'].includes(p.side)&&p.nfl_id&&isValid(p));
  if(!opponents.length)return null;
  const nearest=opponents.map(p=>({p,d:Math.hypot(p.x-selected.x,p.y-selected.y)}))
    .sort((a,b)=>a.d-b.d)[0];
  return {distance:nearest.d,name:nearest.p.name||nearest.p.jersey&&'#'+nearest.p.jersey||nearest.p.nfl_id!,
    playerId:nearest.p.nfl_id!};
}
export function recordedNote(
  replay:HistoricalReplay,currentIndex:number,isGap:boolean,selectedId:string|null,
):RecordedNote {
  const frame=replay.frames[currentIndex];
  if(!frame||isGap)return {
    title:'Observation gap',detail:'No measured positions at this playback instant. The last frame is retained for reference only.',
    provenance:'EVIDENCE_GAP',sourceFrameId:frame?.frame_id??null,sourceTimeSeconds:null,rawEvent:null,
  };
  const latest=latestEvent(replay.frames,currentIndex);
  const nearest=observedNearestOpponent(frame,selectedId);
  if(latest){
    const measurement=nearest
      ? ` Current observed nearest opponent: ${nearest.distance.toFixed(1)} yd. Proximity does not establish the assignment.`
      : '';
    return {title:titleForEvent(latest.event),
      detail:`Source tag “${label(latest.event)}” at frame ${latest.frame.frame_id}.${measurement} Neither tag nor distance proves coaching intent, coverage responsibility or blocking quality.`,
      provenance:'SOURCE_EVENT',sourceFrameId:latest.frame.frame_id,
      sourceTimeSeconds:latest.frame.t_seconds_nominal,rawEvent:latest.event};
  }
  if(nearest)return {
    title:'Observed separation',
    detail:`Nearest opposite-side player ${nearest.name} is ${nearest.distance.toFixed(1)} yards away. Spatial proximity alone does not establish a defensive assignment or a successful block.`,
    provenance:'OBSERVED_GEOMETRY',sourceFrameId:frame.frame_id,
    sourceTimeSeconds:frame.t_seconds_nominal,rawEvent:null,
  };
  return {title:'Tracking in progress',detail:'Only positions and movement from the current recorded frame are available. Select a player to inspect measured opponent separation.',
    provenance:'OBSERVED_GEOMETRY',sourceFrameId:frame.frame_id,
    sourceTimeSeconds:frame.t_seconds_nominal,rawEvent:null};
}
export interface ProximityPoint {frameId:number;time:number;distance:number;}
export interface ProximityChart {paths:ProximityPoint[][];min:number;max:number;observed:number;latest:ProximityPoint|null;}
/** Paths break at absent players, unavailable opponent labels AND source-frame gaps. */
export function opponentProximitySeries(
  replay:HistoricalReplay,selectedId:string|null,currentIndex:number,
):ProximityChart {
  const paths:ProximityPoint[][]=[];
  let active:ProximityPoint[]=[];
  let prevId:number|null=null;
  let observed=0;
  let min=Infinity,max=-Infinity;
  for(let i=0;i<replay.frames.length;i++){
    const frame=replay.frames[i];
    const near=observedNearestOpponent(frame,selectedId);
    if(!near|| (prevId!==null&&frame.frame_id!==prevId+1)){
      if(active.length)paths.push(active);
      active=[];
    }
    prevId=frame.frame_id;
    if(!near)continue;
    const point={frameId:frame.frame_id,time:frame.t_seconds_nominal,distance:near.distance};
    active.push(point);observed++;
    min=Math.min(min,near.distance);max=Math.max(max,near.distance);
  }
  if(active.length)paths.push(active);
  // Do not connect segments across gaps. Downsample only WITHIN each valid segment.
  const sampled=paths.map(path=>{
    if(path.length<=200)return path;
    const step=Math.ceil(path.length/200);
    return path.filter((_,i)=>i%step===0||i===path.length-1);
  });
  const current=replay.frames[currentIndex];
  const now=current?observedNearestOpponent(current,selectedId):null;
  return {paths:sampled,min:observed?min:0,max:observed?max:0,observed,
    latest:now&&current?{frameId:current.frame_id,time:current.t_seconds_nominal,distance:now.distance}:null};
}
export interface ReplayChapter {frameId:number;time:number;title:string;event:string;}
export function replayChapters(replay:HistoricalReplay):ReplayChapter[]{
  return replay.frames.flatMap(frame=>frame.events.filter(Boolean).map(event=>({
    frameId:frame.frame_id,time:frame.t_seconds_nominal,title:titleForEvent(event),event,
  })));
}
