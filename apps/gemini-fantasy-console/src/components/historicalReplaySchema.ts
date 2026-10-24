/** Versioned historical research replay JSON contract. No DOM dependencies. */
export interface TrackedEntity {
  nfl_id: string | null;
  is_ball: boolean;
  team: string | null;
  side: string | null;
  name: string | null;
  jersey: string | null;
  x: number;
  y: number;
  z: null;
  speed_yards_per_s: number | null;
  acceleration_yards_per_s2?: number | null;
  orientation_deg?: number | null;
  movement_dir_deg?: number | null;
}
export interface HistoricalFrame {
  frame_id: number;
  t_seconds_nominal: number;
  players: TrackedEntity[];
  ball: TrackedEntity | null;
  events: string[];
}
export interface PositionQuality {
  policy: 'strict' | 'omit_off_field_with_audit';
  omitted_missing_position_rows: number;
  omitted_off_field_position_rows: number;
  omitted_total_position_rows: number;
  affected_source_frame_ids: number[];
  never_clamped_or_interpolated: true;
}
/** Source-joined official game/plays charting. Declared data, not browser-authenticated. */
export interface HistoricalSourcePlayMetadata {
  provenance: 'PINNED_OFFICIAL_PLAYS_AND_GAMES_CSV' | 'NONCANONICAL_TEST_FIXTURE';
  season: number;
  week: number;
  home_team: string;
  visitor_team: string;
  possession_team: string;
  offense_side: 'home' | 'away';
  quarter: number;
  down: number | null;
  yards_to_go: number | null;
  offense_formation_charted: string | null;
  offense_personnel_charted: string | null;
}
export interface HistoricalReplay {
  source_play_metadata?: HistoricalSourcePlayMetadata;
  possession_team?: string | null;
  position_quality?: PositionQuality;
  data_mode: 'HISTORICAL_RESEARCH';
  tracking_fidelity: 'RECORDED_FRAMES';
  game_id: string;
  play_id: string;
  source: string;
  source_file_sha256: string;
  source_license_identifier: string;
  play_direction: string | null;
  frame_count: number;
  /** Number of original source rows, when exported by the audited adapter. */
  rows?: number;
  missing_frame_count: number;
  frame_coverage: number;
  frames: HistoricalFrame[];
}
export function parseHistoricalReplay(value: unknown): HistoricalReplay {
  if (!value || typeof value !== 'object') throw new Error('Replay JSON must be an object.');
  const o = value as Partial<HistoricalReplay>;
  if (o.data_mode !== 'HISTORICAL_RESEARCH' || o.tracking_fidelity !== 'RECORDED_FRAMES') {
    throw new Error('Only research-labeled recorded tracking files can be imported.');
  }
  if (!Array.isArray(o.frames) || !o.frames.length || o.frames.length > 25000) {
    throw new Error('Replay must include 1 to 25,000 recorded frames.');
  }
  if (typeof o.game_id !== 'string' || typeof o.play_id !== 'string' || typeof o.source_file_sha256 !== 'string' || !/^[a-fA-F0-9]{64}$/.test(o.source_file_sha256)) {
    throw new Error('Replay identity and source SHA-256 are required.');
  }
  if (o.frame_count !== o.frames.length) throw new Error('Recorded frame count does not match the payload.');
  if (o.rows!==undefined && (!Number.isSafeInteger(o.rows)||o.rows<=0))
    throw new Error('Invalid original source row count.');
  for (let i=0;i<o.frames.length;i++) {
    const f = o.frames[i];
    if (!f || !Number.isSafeInteger(f.frame_id) || f.frame_id<1 || !Number.isFinite(f.t_seconds_nominal) || f.t_seconds_nominal < 0 || !Array.isArray(f.players) || f.players.length > 30 || !Array.isArray(f.events)) {
      throw new Error('Invalid recorded frame structure.');
    }
    if (i>0 && (f.frame_id <= o.frames[i-1].frame_id || f.t_seconds_nominal < o.frames[i-1].t_seconds_nominal)) {
      throw new Error('Frames must have increasing source IDs and monotonic timestamps.');
    }
    if (f.events.some(e=>typeof e!=='string' || e.length>128))throw new Error('Invalid source event labels.');
    if (f.ball && (f.ball.nfl_id!==null || f.ball.is_ball!==true))throw new Error('Ball identity is not consistent with source semantics.');
    if (f.players.some(p=>p && (p.is_ball===true || p.nfl_id==null)))throw new Error('Recorded player identities cannot be ball identities.');
    const observedIds=new Set<string>();
    for (const p of [...f.players,...(f.ball?[f.ball]:[])]) {
      if (!p || typeof p!=='object')throw new Error('Invalid tracked entity object.');
      if (p.nfl_id != null && (typeof p.nfl_id!=='string' || !p.nfl_id))throw new Error('Invalid tracking player identity.');
      if (p.nfl_id) {
        if (observedIds.has(p.nfl_id))throw new Error('Duplicate tracked identity in recorded frame.');
        observedIds.add(p.nfl_id);
      }
      for (const field of ['speed_yards_per_s','acceleration_yards_per_s2','orientation_deg','movement_dir_deg'] as const) {
        const n=p[field];
        if (n!=null && (typeof n!=='number' || !Number.isFinite(n)))throw new Error('Invalid numeric tracking observation: '+field);
      }
      if (!p || !Number.isFinite(p.x) || !Number.isFinite(p.y) || p.x<0 || p.x>120 || p.y<0 || p.y>53.3) {
        throw new Error('Tracked entity is missing field-space coordinates.');
      }
    }
  }
  const span=o.frames[o.frames.length-1].frame_id-o.frames[0].frame_id+1;
  if(!Number.isSafeInteger(span)||span<o.frames.length||span>250_000)
    throw new Error('Invalid or unreasonably large source frame span.');
  if (o.missing_frame_count!==span-o.frames.length || Math.abs(o.frame_coverage!-o.frames.length/span)>1e-5)throw new Error('Tracking coverage metadata disagrees with frame IDs.');
  if (typeof o.source!=='string' || !o.source.trim() || typeof o.source_license_identifier!=='string' || !o.source_license_identifier.trim())throw new Error('Tracking source attribution is required.');
  if (typeof o.frame_coverage!=='number' || !Number.isFinite(o.frame_coverage) || o.frame_coverage<=0 || o.frame_coverage>1)throw new Error('Invalid tracking coverage metadata.');
  if(o.source_play_metadata!==undefined){
    const m=o.source_play_metadata;
    const whole=(n:unknown,low:number,high:number)=>Number.isSafeInteger(n)&&Number(n)>=low&&Number(n)<=high;
    const club=(s:unknown)=>typeof s==='string' && /^[A-Z]{2,3}$/.test(s);
    const label=(s:unknown)=>s===null || (typeof s==='string' && s.length>0 && s.length<=120);
    if(!m||typeof m!=='object'
      ||!['PINNED_OFFICIAL_PLAYS_AND_GAMES_CSV','NONCANONICAL_TEST_FIXTURE'].includes(m.provenance)
      ||!whole(m.season,2000,2100)||!whole(m.week,1,22)
      ||!whole(m.quarter,1,5)||!(m.down===null||whole(m.down,1,4))
      ||!(m.yards_to_go===null||whole(m.yards_to_go,0,100))
      ||!club(m.home_team)||!club(m.visitor_team)||m.home_team===m.visitor_team
      ||!club(m.possession_team)||![m.home_team,m.visitor_team].includes(m.possession_team)
      ||m.offense_side!==(m.possession_team===m.home_team?'home':'away')
      ||(o.possession_team!=null&&o.possession_team!==m.possession_team)
      ||!label(m.offense_formation_charted)||!label(m.offense_personnel_charted)){
      throw new Error('Recorded NFL play metadata is internally inconsistent.');
    }
  }
  if (o.position_quality !== undefined) {
    const q=o.position_quality;
    const whole=(n:unknown)=>Number.isSafeInteger(n)&&Number(n)>=0;
    if (!q || !['strict','omit_off_field_with_audit'].includes(q.policy)
        || !whole(q.omitted_missing_position_rows)
        || !whole(q.omitted_off_field_position_rows)
        || !whole(q.omitted_total_position_rows)
        || q.omitted_total_position_rows!==q.omitted_missing_position_rows+q.omitted_off_field_position_rows
        || q.never_clamped_or_interpolated!==true || !Array.isArray(q.affected_source_frame_ids)
        || q.affected_source_frame_ids.length>o.frames.length
        || q.affected_source_frame_ids.some((id,i)=>!Number.isSafeInteger(id) ||
          !o.frames!.some(f=>f.frame_id===id) ||
          (i>0&&id<=q.affected_source_frame_ids[i-1]))
        || (q.omitted_total_position_rows===0)!==(q.affected_source_frame_ids.length===0)) {
      throw new Error('Invalid historical observation exclusion audit.');
    }
  }
  return o as HistoricalReplay;
}
