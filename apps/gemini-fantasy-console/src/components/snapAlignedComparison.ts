/** Historical two-play comparison: source snap events, shared nominal seconds,
 * and observed geometry only. No fabricated frame positions or opponent
 * assignments.  A match of game/source identifiers is consistency, NOT
 * independent authentication of the original NFL CSV files.
 */
import type {HistoricalReplay,HistoricalFrame} from './historicalReplaySchema.ts';
import {sourceSnapIndex} from './football3dMath.ts';
import {frameAtTime} from './trackingTimeline.ts';

export type ComparisonInvalidReason =
  'same-play'|'different-source'|'missing-snap'|'no-overlap';
export interface SnapComparison {
  available:true;
  game_id:string;
  source_file_sha256:string;
  left_snap_frame_id:number;
  right_snap_frame_id:number;
  min_relative_seconds:number;
  max_relative_seconds:number;
  shared_seconds:number;
}
export interface InvalidSnapComparison {
  available:false;
  reason:ComparisonInvalidReason;
}
export type ComparisonAlignment=SnapComparison|InvalidSnapComparison;

export function snapAlignedComparison(
  left:HistoricalReplay,right:HistoricalReplay,
):ComparisonAlignment{
  if(left.game_id===right.game_id&&left.play_id===right.play_id)
    return {available:false,reason:'same-play'};
  if(left.game_id!==right.game_id||
    left.source_file_sha256.toLowerCase()!==right.source_file_sha256.toLowerCase())
    return {available:false,reason:'different-source'};
  const li=sourceSnapIndex(left.frames),ri=sourceSnapIndex(right.frames);
  if(li<0||ri<0)return {available:false,reason:'missing-snap'};
  const la=left.frames[li],ra=right.frames[ri];
  const min=Math.max(
    left.frames[0].t_seconds_nominal-la.t_seconds_nominal,
    right.frames[0].t_seconds_nominal-ra.t_seconds_nominal,
  );
  const max=Math.min(
    left.frames[left.frames.length-1].t_seconds_nominal-la.t_seconds_nominal,
    right.frames[right.frames.length-1].t_seconds_nominal-ra.t_seconds_nominal,
  );
  if(max<min-1e-8)return {available:false,reason:'no-overlap'};
  return {available:true,game_id:left.game_id,source_file_sha256:left.source_file_sha256,
    left_snap_frame_id:la.frame_id,right_snap_frame_id:ra.frame_id,
    min_relative_seconds:min,max_relative_seconds:max,
    shared_seconds:Math.max(0,max-min)};
}

export interface ObservedComparisonFrame {
  nominal_seconds:number;
  source_frame_id:number;
  is_gap:boolean;
  frame:HistoricalFrame|null;
}
export function observedAtRelativeTime(
  replay:HistoricalReplay,relativeSeconds:number,snapIndex?:number,
):ObservedComparisonFrame{
  const snap=snapIndex??sourceSnapIndex(replay.frames);
  if(snap<0||snap>=replay.frames.length||!Number.isFinite(relativeSeconds))
    throw new Error('Source-marked snap and finite relative time are required.');
  const nominal=replay.frames[snap].t_seconds_nominal+relativeSeconds;
  const sample=frameAtTime(replay.frames,nominal);
  return {nominal_seconds:nominal,source_frame_id:sample.source_frame_id,
    is_gap:sample.is_gap,frame:sample.is_gap?null:replay.frames[sample.index]};
}

export interface ObservedPlayerComparison {
  player_id:string|null;
  frame_id:number|null;
  distance_from_snap_yards:number|null;
  nearest_recorded_opponent_yards:number|null;
  geometry_available:boolean;
}
export function compareObservedPlayer(
  replay:HistoricalReplay,relativeSeconds:number,playerId:string|null,
  snapIndex?:number,
):ObservedPlayerComparison{
  const value:ObservedPlayerComparison={player_id:playerId,frame_id:null,
    distance_from_snap_yards:null,nearest_recorded_opponent_yards:null,
    geometry_available:false};
  const current=observedAtRelativeTime(replay,relativeSeconds,snapIndex);
  if(!current.frame||!playerId)return value;
  const player=current.frame.players.find(p=>p.nfl_id===playerId);
  if(!player)return value;
  const snap=replay.frames[snapIndex??sourceSnapIndex(replay.frames)];
  const initial=snap.players.find(p=>p.nfl_id===playerId);
  const opponents=current.frame.players.filter(p=>
    p.nfl_id&&p.side!=='unknown'&&
    (player.side==='offense'||player.side==='defense')&&
    p.side===(player.side==='offense'?'defense':'offense'));
  const nearest=opponents.length?Math.min(...opponents.map(p=>
    Math.hypot(p.x-player.x,p.y-player.y))):null;
  return {...value,frame_id:current.frame.frame_id,geometry_available:true,
    distance_from_snap_yards:initial?
      Math.hypot(player.x-initial.x,player.y-initial.y):null,
    nearest_recorded_opponent_yards:nearest};
}

export function comparisonUnavailableMessage(reason:ComparisonInvalidReason):string{
  switch(reason){
    case 'same-play':return 'Choose two different plays to compare.';
    case 'different-source':return 'Plays must have the same game ID and original tracking-file SHA-256.';
    case 'missing-snap':return 'Both plays need source-recorded snap events; no alignment is estimated.';
    case 'no-overlap':return 'The plays have no overlapping recorded snap-relative time window.';
  }
}
