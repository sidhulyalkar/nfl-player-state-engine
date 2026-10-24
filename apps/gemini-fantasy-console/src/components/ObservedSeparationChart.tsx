import { useMemo } from 'react';
import type { HistoricalFrame } from './historicalReplaySchema';
import {
  nearestOpponentSamples,consecutiveSeparationSegments,nearestOpponentSummary,
} from './observedSeparation';

export function ObservedSeparationChart({frames,selectedId,time}:{
  frames:readonly HistoricalFrame[];selectedId:string|null;time:number;
}){
  const samples=useMemo(()=>nearestOpponentSamples(frames,selectedId),[frames,selectedId]);
  const segments=useMemo(()=>consecutiveSeparationSegments(samples),[samples]);
  const summary=useMemo(()=>nearestOpponentSummary(samples),[samples]);
  const first=frames[0].t_seconds_nominal,last=frames[frames.length-1].t_seconds_nominal;
  const duration=Math.max(.1,last-first);
  const yMax=Math.max(1,Math.ceil((summary.farthest_yards??1)/2)*2);
  const x=(t:number)=>35+(t-first)/duration*465;
  const y=(distance:number)=>139-distance/yMax*108;
  return <section className="gameday-panel" aria-label="Observed nearest opponent separation">
    <div className="gameday-aside-heading"><div><h2>Observed proximity timeline</h2></div></div>
    <p className="gameday-muted">Field-space distance to the nearest *recorded opposing player* by source frame. Opponent identity may change. No assigned coverage or tactical grade.</p>
    {selectedId && summary.observed_frames ? <>
      <svg className="gameday-observed-chart" viewBox="0 0 520 171" role="img"
        aria-label={'Nearest recorded opponent distance across '+summary.observed_frames+' observed frames, with missing samples disconnected'}>
        <rect x="0" y="0" width="520" height="171" rx="9" fill="#0b1b25"/>
        {[0,.25,.5,.75,1].map(fraction=><g key={fraction}>
          <line x1="35" y1={y(yMax*fraction)} x2="500" y2={y(yMax*fraction)}
            stroke="#64838e" strokeDasharray="3 5" strokeOpacity=".34"/>
          <text x="30" y={y(yMax*fraction)+3} fontSize="10" fill="#a1c5c9" textAnchor="end">
            {(yMax*fraction).toFixed(1)}
          </text>
        </g>)}
        {segments.map((seg,i)=>{
          const points=seg.map(s=>x(s.t_seconds_nominal).toFixed(2)+','+y(s.distance_yards!).toFixed(2)).join(' ');
          return seg.length===1?
            <circle key={i} cx={x(seg[0].t_seconds_nominal)} cy={y(seg[0].distance_yards!)}
              r="2.7" fill="#90e5cd"/>:
            <polyline key={i} points={points} fill="none" stroke="#90e5cd" strokeWidth="2.4"
              strokeLinejoin="round" strokeLinecap="round"/>;
        })}
        <line x1={x(Math.min(last,Math.max(first,time)))} y1="18"
          x2={x(Math.min(last,Math.max(first,time)))} y2="142"
          stroke="#f6d18c" strokeWidth="1.4" strokeDasharray="4 4"/>
        <text x="35" y="158" fontSize="10" fill="#9bb7bf">{first.toFixed(1)}s</text>
        <text x="500" y="158" textAnchor="end" fontSize="10" fill="#9bb7bf">{last.toFixed(1)}s</text>
        <text x="490" y="14" textAnchor="end" fontSize="10" fill="#bbd5df">DISTANCE · YD</text>
      </svg>
      <div className="gameday-fact"><span>Closest measured</span><strong>{summary.closest_yards!.toFixed(2)} yd</strong></div>
      <div className="gameday-fact"><span>Frames with both sides observed</span><strong>{summary.observed_frames} / {frames.length}</strong></div>
      <p className="gameday-muted">Disconnected lines indicate absent samples, absent opponents or skipped frame IDs. The vertical marker is playback time, not a fabricated position sample.</p>
    </>:
      <p className="gameday-muted">Select a tracked player with source-declared offense/defense and opposing observations to inspect distance over time.</p>}
  </section>;
}
