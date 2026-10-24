/** Geometric nearest-opponent observations, never defender assignments.
 * Null and skipped source frames are gaps. No samples are interpolated.
 */
import type { HistoricalFrame } from './historicalReplaySchema';

export interface SeparationSample {
  frame_id:number;
  t_seconds_nominal:number;
  distance_yards:number|null;
  opponent_id:string|null;
}

export function nearestOpponentSamples(
  frames:readonly HistoricalFrame[], selectedId:string|null,
):SeparationSample[] {
  return frames.map(frame=>{
    const empty:SeparationSample={
      frame_id:frame.frame_id,t_seconds_nominal:frame.t_seconds_nominal,
      distance_yards:null,opponent_id:null,
    };
    if(!selectedId)return empty;
    const selected=frame.players.find(player=>player.nfl_id===selectedId);
    if(!selected || (selected.side!=='offense' && selected.side!=='defense'))return empty;
    let best:number|null=null;
    let opponent:string|null=null;
    for(const other of frame.players){
      if(!other.nfl_id || other.side!==(selected.side==='offense'?'defense':'offense'))continue;
      const d=Math.hypot(selected.x-other.x,selected.y-other.y);
      if(best===null || d<best){best=d;opponent=other.nfl_id;}
    }
    return {...empty,distance_yards:best,opponent_id:opponent};
  });
}

export function consecutiveSeparationSegments(
  samples:readonly SeparationSample[],
):SeparationSample[][]{
  const segments:SeparationSample[][]=[];
  let current:SeparationSample[]=[];
  for(const item of samples){
    if(item.distance_yards===null){
      if(current.length)segments.push(current);
      current=[];
      continue;
    }
    if(current.length && item.frame_id!==current[current.length-1].frame_id+1){
      segments.push(current);
      current=[];
    }
    current.push(item);
  }
  if(current.length)segments.push(current);
  return segments;
}

export function nearestOpponentSummary(samples:readonly SeparationSample[]){
  const distances=samples.flatMap(sample=>sample.distance_yards===null?[]:[sample.distance_yards]);
  if(!distances.length)return {observed_frames:0,closest_yards:null,farthest_yards:null};
  return {
    observed_frames:distances.length,
    closest_yards:Math.min(...distances),
    farthest_yards:Math.max(...distances),
  };
}
