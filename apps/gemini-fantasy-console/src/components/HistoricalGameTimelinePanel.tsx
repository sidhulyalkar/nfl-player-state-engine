import { useMemo, useState } from 'react';
import { Activity, CircleAlert, Search } from 'lucide-react';
import type { HistoricalReplay } from './historicalReplaySchema';
import type { PlayCatalog } from './historicalPlayCatalog';
import { timelineReplayMatch, type GameTimeline } from './historicalGameTimeline';

interface Props {
  timeline:GameTimeline;
  catalog:PlayCatalog;
  library:readonly HistoricalReplay[];
  onOpen:(replay:HistoricalReplay)=>void;
  onBack:()=>void;
}
const PAGE_SIZE=30;

export function HistoricalGameTimelinePanel({timeline,catalog,library,onOpen,onBack}:Props){
  const [search,setSearch]=useState('');
  const [quarter,setQuarter]=useState('all');
  const [filter,setFilter]=useState<'all'|'loaded'|'unloaded'>('all');
  const [visible,setVisible]=useState(PAGE_SIZE);
  const byPlayId=useMemo(()=>new Map(library.filter(r=>r.game_id===timeline.game_id)
    .map(r=>[r.play_id,r])),[library,timeline.game_id]);
  const matches=useMemo(()=>timeline.plays.filter(p=>{
    const q=search.trim().toLowerCase();
    const replay=byPlayId.get(p.play_id);
    const available=Boolean(replay&&timelineReplayMatch(p,catalog,replay));
    return (quarter==='all'||String(p.quarter)===quarter)
      &&(filter==='all'||(filter==='loaded'?available:!available))
      &&(!q||[p.play_id,p.possession_team,p.description_charted,p.formation_charted,
        p.personnel_charted].some(value=>value?.toLowerCase().includes(q)));
  }),[timeline,catalog,byPlayId,quarter,search,filter]);
  let lastQuarter:number|null=null;
  const shown=matches.slice(0,visible);
  return <section className="gameday-game-timeline" aria-label="Recorded NFL game timeline">
    <div className="gameday-catalog-heading">
      <div>
        <div className="gameday-section-name"><Activity size={15}/> VERIFIED SOURCE METADATA · NOT LIVE</div>
        <h2>{timeline.away_team} at {timeline.home_team} · game timeline</h2>
        <p>Season {timeline.season}, week {timeline.week}. {timeline.play_count} source-matched recorded plays. Charted context is independent of tracking geometry.</p>
      </div>
      <button className="gameday-catalog-close" type="button" onClick={onBack}>Back to play atlas</button>
    </div>
    <div className="gameday-timeline-notice" role="note"><CircleAlert size={15}/>
      No drive IDs are verified by this source. Plays are ordered by official numeric play ID, not inferred possession boundaries.
      Published game-clock and play-description fields are source annotations, not independently synchronized footage.
    </div>
    <div className="gameday-catalog-filters">
      <label><Search size={15}/><input aria-label="Search game plays" value={search} type="search"
        placeholder="Play ID, possession, description, formation…" onChange={e=>{setSearch(e.target.value);setVisible(PAGE_SIZE);}}/></label>
      <select aria-label="Game quarter" value={quarter} onChange={e=>{setQuarter(e.target.value);setVisible(PAGE_SIZE);}}>
        <option value="all">All quarters</option>{[1,2,3,4,5].map(q=><option key={q} value={q}>Quarter {q}</option>)}
      </select>
      <select aria-label="Replay availability" value={filter} onChange={e=>{setFilter(e.target.value as typeof filter);setVisible(PAGE_SIZE);}}>
        <option value="all">All recorded plays</option><option value="loaded">Replay loaded</option><option value="unloaded">Replay not loaded</option>
      </select>
    </div>
    <div className="gameday-catalog-count">{matches.length} source-matched plays · {timeline.qualification_status}</div>
    <div className="gameday-timeline-list">
      {shown.map(p=>{
        const newQuarter=lastQuarter!==p.quarter;lastQuarter=p.quarter;
        const replay=byPlayId.get(p.play_id);
        const loadable=Boolean(replay&&timelineReplayMatch(p,catalog,replay));
        const quality=catalog.plays.find(v=>v.play_id===p.play_id);
        return <div key={p.play_id}>
          {newQuarter&&<div className="gameday-timeline-quarter">Quarter {p.quarter} · charted game context</div>}
          <article className="gameday-timeline-play">
            <div className="gameday-timeline-id"><strong>{p.play_id}</strong><small>Play ID</small></div>
            <div className="gameday-timeline-info">
              <div className="gameday-timeline-situation"><strong>{p.down===0?'Down not charted':p.down+' & '+p.yards_to_go}</strong>
                <span>{p.possession_team} · {p.game_clock_charted??'clock unavailable'}</span></div>
              <p>{p.description_charted??'No published play description'}</p>
              <small>{p.formation_charted?'Formation: '+p.formation_charted+' · ':''}
                {p.personnel_charted?'Personnel: '+p.personnel_charted:'Personnel not charted'}</small>
              {quality&&(quality.unrenderable_position_rows>0||quality.missing_frame_ids>0)
                &&<small className="gameday-catalog-caution">Tracking gaps: {quality.unrenderable_position_rows} excluded positions,
                    {quality.missing_frame_ids} missing frames</small>}
            </div>
            <div className="gameday-timeline-action">{loadable&&replay
              ?<button type="button" onClick={()=>onOpen(replay)}>Open 3D replay</button>
              :<span>{replay?'Replay mismatch: not opened':'Replay JSON not loaded'}</span>}</div>
          </article>
        </div>;
      })}
    </div>
    {!matches.length&&<p className="gameday-muted">No source plays match these filters.</p>}
    {visible<matches.length&&<button type="button" className="gameday-catalog-more"
      onClick={()=>setVisible(n=>n+PAGE_SIZE)}>Show more plays ({shown.length} of {matches.length})</button>}
    <p className="gameday-catalog-caveat">Metadata is joined from source-identical official games.csv and plays.csv.
      Browser SHA labels are source claims, not cryptographic revalidation of the local CSVs.
      No inferred drives, tracking coordinates, live state, ball height, tactical grades or media reuse rights.</p>
  </section>;
}
