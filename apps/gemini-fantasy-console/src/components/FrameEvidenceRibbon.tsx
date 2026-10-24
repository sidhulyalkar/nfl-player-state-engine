import {useMemo} from 'react';
import type {HistoricalReplay} from './historicalReplaySchema';
import {buildFrameEvidenceOverview, type EvidenceStatus} from './frameEvidence';

const tones:Record<EvidenceStatus,string>={
  recorded:'#79d3b9',
  'ball-unobserved':'#88aec4',
  'position-excluded':'#f2be7a',
  'source-gap':'#e77f7f',
};

/** 100-bin aggregation regardless of frame span. The entire ribbon is a source
 * quality overview, NOT a representation of unobserved player positions.
 */
export function FrameEvidenceRibbon({replay,time}:{
  replay:HistoricalReplay;
  time:number;
}){
  const overview=useMemo(()=>buildFrameEvidenceOverview(replay),[replay]);
  const bars=useMemo(()=>overview.bins.map((b,i)=>(
    <rect key={i} x={25+i*4.7} y="18" width="4.5" height="18" rx="1.1"
      fill={tones[b.status]}>
      <title>{'Source frames '+b.start_frame_id+'–'+b.end_frame_id+
        ': '+b.recorded_frames+' recorded, '+b.missing_source_frames+' absent, '+
        b.frames_with_excluded_positions+' with omitted positions, '+
        b.frames_without_recorded_ball+' without ball coordinates'}</title>
    </rect>
  )),[overview]);
  const first=replay.frames[0].t_seconds_nominal;
  const cursor=Math.min(1,Math.max(0,(time-first)/
    Math.max(0.1,replay.frames[replay.frames.length-1].t_seconds_nominal-first)));
  const missing=overview.missing_source_frames,omitted=overview.frames_with_excluded_positions;
  return <section className="gameday-panel" aria-label="Recorded frame evidence timeline">
    <div className="gameday-aside-heading"><div><h2>Source completeness</h2></div></div>
    <p className="gameday-muted">100-bin overview of recorded frame IDs. A missing source frame is not the same as an excluded player position or unrecorded ball coordinates.</p>
    <svg viewBox="0 0 520 58" width="100%" role="img"
      aria-label={missing+' missing source frame IDs, '+omitted+' frames with excluded position rows, '+overview.frames_without_recorded_ball+' frames with no recorded ball position'}>
      <rect x="25" y="17" width="470" height="20" fill="#17313b" rx="2"/>
      {bars}
      <line x1={25+cursor*470} x2={25+cursor*470} y1="8" y2="45"
        stroke="#faf0d4" strokeWidth="1.6"/>
      <text x="25" y="54" fill="#a3c5ce" fontSize="10">Frame {overview.first_frame_id}</text>
      <text x="495" y="54" fill="#a3c5ce" fontSize="10" textAnchor="end">Frame {overview.last_frame_id}</text>
    </svg>
    <div className="gameday-evidence-legend">
      {([
        ['recorded','Other recorded frames'],['ball-unobserved','Ball x/y unrecorded'],
        ['position-excluded','Excluded position row'],['source-gap','Missing source frame'],
      ] as const).map(([status,label])=><span key={status}>
        <i style={{backgroundColor:tones[status]}}/>{label}
      </span>)}
    </div>
    <div className="gameday-fact"><span>Recorded / expected frames</span><strong>{overview.recorded_frames} / {overview.recorded_frames+missing}</strong></div>
    <div className="gameday-fact"><span>Missing source frame IDs</span><strong>{missing}</strong></div>
    <div className="gameday-fact"><span>Frames with excluded position rows</span><strong>{omitted}</strong></div>
    <div className="gameday-fact"><span>Frames lacking a recorded ball x/y</span><strong>{overview.frames_without_recorded_ball}</strong></div>
    <p className="gameday-muted">Priority color shows the most severe evidence limitation in each aggregate bin. Hover a segment for exact counts. Gaps are not filled, and missing ball samples do not prove the ball was absent.</p>
  </section>;
}
