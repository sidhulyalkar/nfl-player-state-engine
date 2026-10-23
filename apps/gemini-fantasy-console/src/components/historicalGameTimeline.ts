/** Verified-metadata sidecar. No drive boundaries, tracking frames or inference. */
import type { PlayCatalog } from './historicalPlayCatalog';

export interface GameTimelinePlay {
  game_id:string;
  play_id:string;
  quarter:number;
  down:number;
  yards_to_go:number;
  possession_team:string;
  offense_side:'home'|'away';
  game_clock_charted:string|null;
  yardline_side_charted:string|null;
  yardline_number_charted:number|null;
  description_charted:string|null;
  formation_charted:string|null;
  personnel_charted:string|null;
  source_tracking_rows:number;
}
export interface GameTimeline {
  schema_version:1;
  data_mode:'HISTORICAL_RESEARCH_GAME_TIMELINE';
  qualification_status:'SOURCE_AND_STRUCTURE_QUALIFIED_VIDEO_PENDING'|'SYNTHETIC_OR_NONCANONICAL_FIXTURE_ONLY';
  game_id:string;
  season:number;
  week:number;
  home_team:string;
  away_team:string;
  tracking_source_sha256:string;
  plays_source_sha256:string;
  games_source_sha256:string;
  source_commit:string|null;
  play_count:number;
  positions_included:false;
  drive_boundaries_verified:false;
  source_video_alignment_verified:false;
  commercial_reuse_authorized:false;
  model_training_authorized:false;
  plays:GameTimelinePlay[];
}
const digest=(v:unknown)=>typeof v==='string'&&/^[a-f0-9]{64}$/i.test(v);
const integer=(v:unknown,min:number,max:number)=>Number.isSafeInteger(v)&&Number(v)>=min&&Number(v)<=max;
const nullableText=(v:unknown,max=500)=>v===null||(typeof v==='string'&&v.trim().length>0&&v.length<=max&&!/[\x00-\x08\x0B-\x1F\x7F]/.test(v));
const gameClock=(v:unknown)=>v===null||(typeof v==='string'&&/^(?:[0-9]|[0-5][0-9]):[0-5][0-9]$/.test(v));
export function parseGameTimeline(value:unknown,catalog:PlayCatalog):GameTimeline {
  if(!value||typeof value!=='object')throw new Error('Game timeline JSON must be an object.');
  const root=value as Partial<GameTimeline>;
  if(root.schema_version!==1||root.data_mode!=='HISTORICAL_RESEARCH_GAME_TIMELINE'
      ||root.positions_included!==false||root.drive_boundaries_verified!==false
      ||root.source_video_alignment_verified!==false
      ||root.commercial_reuse_authorized!==false||root.model_training_authorized!==false)
    throw new Error('Game timeline must be position-free, non-live, and must not assert verified drives or model authority.');
  if(!digest(root.tracking_source_sha256)||!digest(root.plays_source_sha256)||!digest(root.games_source_sha256)
      ||root.tracking_source_sha256!==catalog.source_sha256||root.game_id!==catalog.game_id
      ||typeof root.home_team!=='string'||!root.home_team.trim()
      ||typeof root.away_team!=='string'||!root.away_team.trim()
      ||root.home_team===root.away_team||!integer(root.season,2000,2100)
      ||!integer(root.week,1,22))
    throw new Error('Timeline source identifiers do not match the loaded recorded-play catalog.');
  if(root.qualification_status!=='SOURCE_AND_STRUCTURE_QUALIFIED_VIDEO_PENDING'
      &&root.qualification_status!=='SYNTHETIC_OR_NONCANONICAL_FIXTURE_ONLY')
    throw new Error('Unsupported timeline qualification status.');
  if(root.qualification_status==='SOURCE_AND_STRUCTURE_QUALIFIED_VIDEO_PENDING'
      &&root.source_commit!=='9ad0b4b2ea36697e29e44e2399512cc1ce70358c')
    throw new Error('Official timeline must declare the pinned source revision.');
  if(!Array.isArray(root.plays)||root.play_count!==root.plays.length
      ||root.plays.length!==catalog.plays.length||root.plays.length>1000)
    throw new Error('Timeline play coverage must equal the source catalog.');
  const byId=new Map(catalog.plays.map(p=>[p.play_id,p]));
  const seen=new Set<string>();
  let last=0;
  for(const p of root.plays){
    if(!p||typeof p!=='object'||['frames','players','tracking','x','y','ball'].some(key=>key in p))
      throw new Error('Timeline cannot include tracking frames or coordinates.');
    const catalogPlay=byId.get(p.play_id);
    const id=Number(p.play_id);
    if(p.game_id!==root.game_id||!Number.isSafeInteger(id)||id<=last
        ||seen.has(p.play_id)||!catalogPlay
        ||p.source_tracking_rows!==catalogPlay.source_rows)
      throw new Error('Timeline play identities or source-row counts are inconsistent.');
    seen.add(p.play_id);last=id;
    if(!integer(p.quarter,1,5)||!integer(p.down,0,4)||!integer(p.yards_to_go,0,100)
        ||![root.home_team,root.away_team].includes(p.possession_team)
        ||p.offense_side!==(p.possession_team===root.home_team?'home':'away')
        ||!gameClock(p.game_clock_charted)
        ||!nullableText(p.yardline_side_charted,8)
        ||!((p.yardline_side_charted===null&&p.yardline_number_charted===null)
          ||([root.home_team,root.away_team].includes(p.yardline_side_charted as string)
            &&integer(p.yardline_number_charted,0,50)))
        ||!nullableText(p.description_charted)
        ||!nullableText(p.formation_charted,120)||!nullableText(p.personnel_charted,120))
      throw new Error('Invalid or unverified game situation metadata.');
  }
  return root as GameTimeline;
}

export function timelineReplayMatch(play:GameTimelinePlay,catalog:PlayCatalog,replay:{
  game_id:string;play_id:string;frame_count:number;missing_frame_count:number;
  source_file_sha256:string;rows?:number;
}):boolean {
  const catalogPlay=catalog.plays.find(p=>p.play_id===play.play_id);
  return Boolean(catalogPlay&&play.game_id===replay.game_id
    &&catalog.source_sha256===replay.source_file_sha256
    &&catalogPlay.recorded_frames===replay.frame_count
    &&catalogPlay.missing_frame_ids===replay.missing_frame_count
    &&(replay.rows===undefined||play.source_tracking_rows===replay.rows));
}
