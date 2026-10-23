import { useMemo, useState } from 'react';
import { Activity, CircleAlert, Search } from 'lucide-react';
import type { HistoricalReplay } from './historicalReplaySchema';
import { catalogMatchesReplay } from './historicalPlayCatalog';
import type { PlayCatalog } from './historicalPlayCatalog';

interface Props {
  catalog:PlayCatalog;
  library:readonly HistoricalReplay[];
  onOpen:(replay:HistoricalReplay)=>void;
  onClose:()=>void;
}
const PAGE_SIZE=24;
export function HistoricalPlayCatalogPanel({catalog,library,onOpen,onClose}:Props){
  const [search,setSearch]=useState('');
  const [quality,setQuality]=useState<'all'|'clean'|'caution'>('all');
  const [sort,setSort]=useState<'play'|'longest'>('play');
  const [visible,setVisible]=useState(PAGE_SIZE);
  const matches=useMemo(()=>{
    const q=search.trim().toLowerCase();
    const found=catalog.plays.filter(p=>
      (!q||p.play_id.toLowerCase().includes(q)||
        Object.keys(p.source_events).some(e=>e.toLowerCase().includes(q))) &&
      (quality==='all'||(quality==='clean'?p.unrenderable_position_rows===0:
        p.unrenderable_position_rows>0||p.missing_frame_ids>0)));
    if(sort==='longest')found.sort((a,b)=>b.recorded_frames-a.recorded_frames||
      Number(a.play_id)-Number(b.play_id));
    else found.sort((a,b)=>Number(a.play_id)-Number(b.play_id));
    return found;
  },[catalog,search,quality,sort]);
  const byPlayId=new Map(library.filter(r=>r.game_id===catalog.game_id)
    .map(r=>[r.play_id,r]));
  const openable=catalog.plays.filter(p=> {
    const r=byPlayId.get(p.play_id);
    return r&&r.source_file_sha256===catalog.source_sha256&&catalogMatchesReplay(p,r);
  }).length;
  return <section className="gameday-catalog" aria-label="Recorded NFL play catalog">
    <div className="gameday-catalog-heading">
      <div><div className="gameday-section-name"><Activity size={15}/> SOURCE METADATA ONLY</div>
        <h2>Recorded game play atlas</h2>
        <p>Game {catalog.game_id} · {catalog.play_count} plays · {openable} matching loaded replays. Search by play ID or source event.</p>
      </div>
      <button type="button" className="gameday-catalog-close" onClick={onClose}>Hide catalog</button>
    </div>
    <div className="gameday-catalog-filters">
      <label><Search size={15}/> <input aria-label="Search recorded plays and events" type="search"
        placeholder="Play ID, touchdown, ball_snap…" value={search}
        onChange={e=>{setSearch(e.target.value);setVisible(PAGE_SIZE);}}/></label>
      <select aria-label="Catalog data quality" value={quality}
        onChange={e=>{setQuality(e.target.value as typeof quality);setVisible(PAGE_SIZE);}}>
        <option value="all">All observations</option>
        <option value="clean">No undrawable positions</option>
        <option value="caution">Has evidence gaps</option>
      </select>
      <select aria-label="Catalog sort order" value={sort} onChange={e=>setSort(e.target.value as typeof sort)}>
        <option value="play">Play ID</option>
        <option value="longest">Longest first</option>
      </select>
    </div>
    <div className="gameday-catalog-count">{matches.length} source plays match</div>
    <div className="gameday-catalog-results">
      {matches.slice(0,visible).map(p=>{
        const candidate=byPlayId.get(p.play_id);
        const loadable=candidate&&candidate.source_file_sha256===catalog.source_sha256
          &&catalogMatchesReplay(p,candidate);
        const events=Object.keys(p.source_events);
        return <article key={p.play_id} className="gameday-catalog-play">
          <div className="gameday-catalog-play-main">
            <strong>Play {p.play_id}</strong>
            <small>{p.recorded_frames} frames · {p.duration_seconds_nominal.toFixed(1)}s · {p.unique_players} distinct players</small>
            <div className="gameday-catalog-events">{events.length?events.map(label=>
              <span key={label} title={p.source_events[label].join(', ')}>
                {label.replaceAll('_',' ')}
              </span>):<span>No recorded event labels</span>}</div>
          </div>
          <div className="gameday-catalog-play-status">
            {p.unrenderable_position_rows||p.missing_frame_ids?
              <span className="gameday-catalog-caution"><CircleAlert size={13}/>
                {p.unrenderable_position_rows} excluded positions · {p.missing_frame_ids} missing frames</span>:
              <span className="gameday-catalog-clean">All positions on field · no frame gaps</span>}
            {loadable ? <button type="button" onClick={()=>onOpen(candidate)}>Open recorded replay</button> :
              <small>{candidate?'Loaded replay identity or source hash differs':'Import this play’s replay JSON to inspect positions'}</small>}
          </div>
        </article>;
      })}
    </div>
    {!matches.length&&<p className="gameday-muted">No plays match. Try a different event or quality filter.</p>}
    {visible<matches.length&&<button type="button" className="gameday-catalog-more"
      onClick={()=>setVisible(n=>n+PAGE_SIZE)}>Show more plays ({Math.min(visible,matches.length)} of {matches.length})</button>}
    <p className="gameday-catalog-caveat">This local catalog contains event/frame summaries only. The recorded player coordinates remain in separately loaded research JSONs. Source identity is declared by the file, not independently authenticated in the browser. Coverage assignments, ball height and source-video alignment are not inferred.</p>
  </section>;
}
