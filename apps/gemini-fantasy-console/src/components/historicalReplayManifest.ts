/** Local research bundle verification. Hashes authenticate exported JSON bytes
 * against their selected manifest; they DO NOT authenticate the original NFL CSVs.
 */
import { parseHistoricalReplay, type HistoricalReplay } from './historicalReplaySchema.ts';

const sha256Pattern=/^[0-9a-f]{64}$/i;
const sha1Pattern=/^[0-9a-f]{40}$/i;
const plainObject=(value:unknown):value is Record<string,unknown>=>
  value!==null && typeof value==='object' && !Array.isArray(value);
const positive=(n:unknown)=>Number.isSafeInteger(n)&&Number(n)>0;
const natural=(n:unknown)=>Number.isSafeInteger(n)&&Number(n)>=0;

export interface ReplaySessionEntry {
  play_id:string;
  file:string;
  sha256:string;
  source_rows:number;
  recorded_frames:number;
  missing_source_frames:number;
  omitted_position_rows:number;
  possession_team:string;
  metadata_provenance:'PINNED_OFFICIAL_PLAYS_AND_GAMES_CSV'|'NONCANONICAL_TEST_FIXTURE';
}
export interface ReplaySessionManifest {
  schema_version:1;
  data_mode:'HISTORICAL_RESEARCH_BATCH_MANIFEST';
  qualification_status:'PINNED_SOURCE_AND_PLAY_METADATA_VIDEO_PENDING'|'NONCANONICAL_FIXTURE_ONLY';
  game_id:string;
  source_file_sha256:string;
  source_identities:Record<'tracking'|'games'|'plays', {
    file:string;bytes:number;sha256:string;git_blob_sha1:string;identity_match:true
  }>;
  source_video_alignment_verified:false;
  model_training_authorized:false;
  commercial_reuse_authorized:false;
  license_declaration:string;
  play_count:number;
  plays:ReplaySessionEntry[];
}

export interface LocalReplayFile {
  name:string;
  arrayBuffer():Promise<ArrayBuffer>;
}

export function parseReplaySessionManifest(value:unknown):ReplaySessionManifest {
  if(!plainObject(value) || value.schema_version!==1 ||
    value.data_mode!=='HISTORICAL_RESEARCH_BATCH_MANIFEST' ||
    !['PINNED_SOURCE_AND_PLAY_METADATA_VIDEO_PENDING','NONCANONICAL_FIXTURE_ONLY'].includes(String(value.qualification_status)) ||
    !/^[0-9]{10}$/.test(String(value.game_id)) ||
    typeof value.source_file_sha256!=='string' || !sha256Pattern.test(value.source_file_sha256) ||
    value.source_video_alignment_verified!==false ||
    value.model_training_authorized!==false || value.commercial_reuse_authorized!==false ||
    typeof value.license_declaration!=='string' || !value.license_declaration.trim() ||
    value.license_declaration.length>256 ||
    !Array.isArray(value.plays) || value.plays.length<1 || value.plays.length>12 ||
    value.play_count!==value.plays.length) {
    throw new Error('Invalid research session manifest or missing rights/evidence limitations.');
  }
  if(!plainObject(value.source_identities) ||
    Object.keys(value.source_identities).sort().join(',')!=='games,plays,tracking') {
    throw new Error('Session manifest must declare exactly three source identities.');
  }
  for(const identity of Object.values(value.source_identities)){
    if(!plainObject(identity) || identity.identity_match!==true ||
      typeof identity.file!=='string' || !/^[a-zA-Z0-9_.-]+\.csv$/.test(identity.file) ||
      !positive(identity.bytes) || typeof identity.sha256!=='string' || !sha256Pattern.test(identity.sha256) ||
      typeof identity.git_blob_sha1!=='string' || !sha1Pattern.test(identity.git_blob_sha1)) {
      throw new Error('Invalid source identity declaration in session manifest.');
    }
  }
  const tracking=value.source_identities.tracking as Record<string,unknown>;
  if(tracking.sha256!==value.source_file_sha256)
    throw new Error('Session tracking SHA-256 does not match the source identity declaration.');
  const official=value.qualification_status==='PINNED_SOURCE_AND_PLAY_METADATA_VIDEO_PENDING';
  const seen=new Set<string>();
  for(const item of value.plays){
    if(!plainObject(item) || typeof item.play_id!=='string' ||
      !/^[0-9]{1,10}$/.test(item.play_id) || seen.has(item.play_id) ||
      item.file!==value.game_id+'-'+item.play_id+'-research-replay.json' ||
      typeof item.sha256!=='string' || !sha256Pattern.test(item.sha256) ||
      !positive(item.source_rows) || !positive(item.recorded_frames) ||
      !natural(item.missing_source_frames) || !natural(item.omitted_position_rows) ||
      typeof item.possession_team!=='string' || !/^[A-Z]{2,3}$/.test(item.possession_team) ||
      item.metadata_provenance!==(official?'PINNED_OFFICIAL_PLAYS_AND_GAMES_CSV':'NONCANONICAL_TEST_FIXTURE')) {
      throw new Error('Invalid or duplicate play entry in research session manifest.');
    }
    seen.add(item.play_id);
  }
  return value as unknown as ReplaySessionManifest;
}

function bytesHex(bytes:Uint8Array):string {
  return Array.from(bytes,byte=>byte.toString(16).padStart(2,'0')).join('');
}

/** Fail closed unless every replay file matches the manifest, by raw-byte SHA
 * and by parsed semantic metadata. Never partially publish a verified session.
 */
export async function verifyReplaySessionFiles(
  manifest:ReplaySessionManifest, files:readonly LocalReplayFile[],
):Promise<HistoricalReplay[]> {
  const expected=new Set(manifest.plays.map(entry=>entry.file));
  if(files.length!==expected.size)
    throw new Error('Select every replay JSON listed by manifest.json, with no extra files.');
  const byName=new Map<string,LocalReplayFile>();
  for(const file of files){
    if(!expected.has(file.name) || byName.has(file.name))
      throw new Error('Unexpected or duplicate replay file: '+file.name);
    byName.set(file.name,file);
  }
  if(!globalThis.crypto?.subtle)
    throw new Error('Secure browser SHA-256 verification is unavailable; session was not imported.');
  const result:HistoricalReplay[]=[];
  for(const entry of manifest.plays){
    const file=byName.get(entry.file);
    if(!file)throw new Error('Session is missing '+entry.file);
    const bytes=new Uint8Array(await file.arrayBuffer());
    const digest=await globalThis.crypto.subtle.digest('SHA-256',bytes);
    if(bytesHex(new Uint8Array(digest)).toLowerCase()!==entry.sha256.toLowerCase())
      throw new Error('Replay SHA-256 mismatch: '+entry.file);
    let raw:unknown;
    try{raw=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes));}
    catch {throw new Error('Invalid UTF-8 replay JSON: '+entry.file);}
    const replay=parseHistoricalReplay(raw);
    const sourceRows=plainObject(raw)?raw.rows:undefined;
    if(replay.game_id!==manifest.game_id || replay.play_id!==entry.play_id ||
      replay.source_file_sha256.toLowerCase()!==manifest.source_file_sha256.toLowerCase() ||
      replay.frame_count!==entry.recorded_frames ||
      replay.missing_frame_count!==entry.missing_source_frames ||
      sourceRows!==entry.source_rows ||
      replay.source_license_identifier!==manifest.license_declaration ||
      !replay.position_quality ||
      replay.position_quality.omitted_total_position_rows!==entry.omitted_position_rows ||
      replay.possession_team!==entry.possession_team ||
      replay.source_play_metadata?.possession_team!==entry.possession_team ||
      replay.source_play_metadata?.provenance!==entry.metadata_provenance){
      throw new Error('Replay conflicts with research manifest: '+entry.file);
    }
    result.push(replay);
  }
  return result;
}
