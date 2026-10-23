/** Position-free historical research play catalog. Never loads tracking trajectories. */
export interface PlayCatalogEntry {
  game_id: string;
  play_id: string;
  source_rows: number;
  recorded_frames: number;
  missing_frame_ids: number;
  coverage_ratio: number;
  first_frame_id: number;
  last_frame_id: number;
  duration_seconds_nominal: number;
  unique_players: number;
  max_players_per_frame: number;
  ball_recorded_frames: number;
  source_events: Record<string, number[]>;
  unrenderable_position_rows: number;
  off_field_rows: number;
  missing_xy_rows: number;
  affected_source_frame_ids: number[];
}
export interface PlayCatalog {
  schema_version: 1;
  data_mode: 'HISTORICAL_RESEARCH_METADATA_ONLY';
  qualification_status?: string;
  game_id: string;
  source: string;
  source_sha256: string;
  source_bytes: number;
  source_rows: number;
  play_count: number;
  positions_included: false;
  source_video_alignment_verified: false;
  plays: PlayCatalogEntry[];
}
const whole=(v:unknown)=>Number.isSafeInteger(v)&&Number(v)>=0;
const posInt=(v:unknown)=>Number.isSafeInteger(v)&&Number(v)>0;
const sortedUnique=(a:unknown,within?:[number,number])=>
  Array.isArray(a)&&a.length<=25000&&a.every((v,i)=>posInt(v)
    &&(within===undefined||(v>=within[0]&&v<=within[1]))
    &&(i===0||v>a[i-1]));
export function parsePlayCatalog(value:unknown):PlayCatalog {
  if (!value || typeof value!=='object') throw new Error('Play catalog must be an object.');
  const root=value as Partial<PlayCatalog>;
  if(root.schema_version!==1||root.data_mode!=='HISTORICAL_RESEARCH_METADATA_ONLY'
      ||root.positions_included!==false||root.source_video_alignment_verified!==false)
    throw new Error('Only position-free historical research catalogs can be imported.');
  if(typeof root.game_id!=='string'||!root.game_id.trim()
      ||typeof root.source!=='string'||!root.source.trim()
      ||typeof root.source_sha256!=='string'||!/^[a-fA-F0-9]{64}$/.test(root.source_sha256)
      ||!posInt(root.source_bytes)||!posInt(root.source_rows))
    throw new Error('Catalog is missing source identity and SHA-256 evidence.');
  if(!Array.isArray(root.plays)||!root.plays.length||root.plays.length>1000
      ||root.play_count!==root.plays.length)
    throw new Error('Invalid catalog play count (maximum 1,000).');
  const ids=new Set<string>();
  let sourceRows=0;
  for(const play of root.plays){
    if(!play||typeof play!=='object'||'frames' in play ||'players' in play
        ||'tracking' in play||'x' in play||'y' in play)
      throw new Error('Catalog must not contain per-player positions or frames.');
    if(typeof play.play_id!=='string'||!play.play_id.trim()||play.game_id!==root.game_id
        ||ids.has(play.play_id))throw new Error('Invalid or duplicate catalog play identity.');
    ids.add(play.play_id);
    if(![play.source_rows,play.recorded_frames,play.first_frame_id,play.last_frame_id].every(posInt)
        ||![play.missing_frame_ids,play.unique_players,play.max_players_per_frame,play.ball_recorded_frames,
          play.unrenderable_position_rows,play.off_field_rows,play.missing_xy_rows].every(whole)
        ||play.last_frame_id<play.first_frame_id
        ||play.last_frame_id-play.first_frame_id+1-play.recorded_frames!==play.missing_frame_ids
        ||play.ball_recorded_frames>play.recorded_frames
        ||play.max_players_per_frame>30
        ||play.off_field_rows+play.missing_xy_rows!==play.unrenderable_position_rows
        ||play.unrenderable_position_rows>play.source_rows
        ||!Number.isFinite(play.coverage_ratio)||Math.abs(play.coverage_ratio-
           play.recorded_frames/(play.recorded_frames+play.missing_frame_ids))>1e-4
        ||!Number.isFinite(play.duration_seconds_nominal)
        ||Math.abs(play.duration_seconds_nominal-(play.last_frame_id-play.first_frame_id)/10)>1e-3
        ||!sortedUnique(play.affected_source_frame_ids,[play.first_frame_id,play.last_frame_id])
        ||(play.affected_source_frame_ids.length===0)!==(play.unrenderable_position_rows===0))
      throw new Error('Catalog frame or position-quality metadata is inconsistent.');
    if(!play.source_events||typeof play.source_events!=='object'||Array.isArray(play.source_events)
        ||Object.entries(play.source_events).some(([label,frames])=>
           label.length>128||!label.length||!sortedUnique(frames,[play.first_frame_id,play.last_frame_id])))
      throw new Error('Invalid event evidence in play catalog.');
    sourceRows+=play.source_rows;
  }
  if(sourceRows!==root.source_rows)throw new Error('Catalog source record totals disagree.');
  return root as PlayCatalog;
}
export function catalogMatchesReplay(
  play:PlayCatalogEntry,
  replay:{game_id:string;play_id:string;frame_count:number;missing_frame_count:number;rows?:number},
):boolean {
  return play.game_id===replay.game_id&&play.play_id===replay.play_id
    &&play.recorded_frames===replay.frame_count&&play.missing_frame_ids===replay.missing_frame_count
    &&(replay.rows===undefined||play.source_rows===replay.rows);
}
