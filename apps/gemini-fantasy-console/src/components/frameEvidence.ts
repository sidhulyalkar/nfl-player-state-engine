/** Frame-ID based evidence overview for historical NFL research replays.
 * Source-gap counts are distinct from excluded x/y observations and missing
 * ball positions. Never interpolate or assume a missing ball was absent in play.
 */
import type { HistoricalReplay } from './historicalReplaySchema';

export type EvidenceStatus='recorded'|'ball-unobserved'|'position-excluded'|'source-gap';
export interface EvidenceBin {
  start_frame_id:number;
  end_frame_id:number;
  recorded_frames:number;
  missing_source_frames:number;
  frames_with_excluded_positions:number;
  frames_without_recorded_ball:number;
  status:EvidenceStatus;
}
export interface EvidenceOverview {
  first_frame_id:number;
  last_frame_id:number;
  recorded_frames:number;
  missing_source_frames:number;
  frames_with_excluded_positions:number;
  frames_without_recorded_ball:number;
  bins:EvidenceBin[];
}

export function buildFrameEvidenceOverview(
  replay:Pick<HistoricalReplay,'frames'|'position_quality'>,
  maxBins=100,
):EvidenceOverview{
  const frames=replay.frames;
  if(!frames.length||!Number.isSafeInteger(maxBins)||maxBins<1||maxBins>250)
    throw new Error('Evidence timeline needs recorded frames and a valid resolution.');
  const first=frames[0].frame_id;
  const last=frames[frames.length-1].frame_id;
  const span=last-first+1;
  if(!Number.isSafeInteger(span)||span<frames.length||span>250_000)
    throw new Error('Invalid or unreasonably large source frame span.');
  const excluded=new Set(replay.position_quality?.affected_source_frame_ids??[]);
  const count=Math.min(maxBins,span);
  const bins:EvidenceBin[]=[];
  let index=0;
  let totalExcluded=0,totalNoBall=0;
  for(let i=0;i<count;i++){
    const binStart=first+Math.floor(i*span/count);
    const binEnd=first+Math.floor((i+1)*span/count)-1;
    let recorded=0,excludedCount=0,unobservedBall=0;
    while(index<frames.length&&frames[index].frame_id<=binEnd){
      const frame=frames[index++];
      recorded++;
      if(excluded.has(frame.frame_id))excludedCount++;
      if(frame.ball===null)unobservedBall++;
    }
    const missing=binEnd-binStart+1-recorded;
    totalExcluded+=excludedCount;totalNoBall+=unobservedBall;
    const status:EvidenceStatus=missing?'source-gap':
      excludedCount?'position-excluded':unobservedBall?'ball-unobserved':'recorded';
    bins.push({
      start_frame_id:binStart,end_frame_id:binEnd,recorded_frames:recorded,
      missing_source_frames:missing,frames_with_excluded_positions:excludedCount,
      frames_without_recorded_ball:unobservedBall,status,
    });
  }
  if(index!==frames.length)throw new Error('Evidence bins failed to consume source frames.');
  return {
    first_frame_id:first,last_frame_id:last,recorded_frames:frames.length,
    missing_source_frames:span-frames.length,
    frames_with_excluded_positions:totalExcluded,
    frames_without_recorded_ball:totalNoBall,bins,
  };
}
