/** Private, read-only preflight for the exact local export directory.
 * It never uploads tracking or includes player coordinates in its report.
 * The browser independently checks hashes and semantic replay contracts.
 */
import {createHash} from 'node:crypto';
import {createReadStream} from 'node:fs';
import {lstat,readFile,readdir} from 'node:fs/promises';
import path from 'node:path';

const SHA=/^[0-9a-f]{64}$/i;
const ID=/^[0-9]{10}$/;
const PLAY=/^[0-9]{1,10}$/;
const MAX_MANIFEST=2_000_000;
const MAX_FILE=25_000_000;
const MAX_BATCH=50_000_000;

export async function inspectPrivateResearchSession(
  directory,{expectedPlayCount=null,licenseIdentifier=null}={},
){
  const root=path.resolve(directory);
  const rootStat=await lstat(root);
  if(!rootStat.isDirectory()||rootStat.isSymbolicLink())
    throw new Error('Session root must be a real local directory.');
  const manifestPath=path.join(root,'manifest.json');
  const mst=await lstat(manifestPath);
  if(!mst.isFile()||mst.isSymbolicLink()||mst.size>MAX_MANIFEST)
    throw new Error('Manifest is missing, symlinked or oversized.');
  const m=JSON.parse(await readFile(manifestPath,'utf8'));
  if(m?.schema_version!==1||m.data_mode!=='HISTORICAL_RESEARCH_BATCH_MANIFEST'||
    !ID.test(m.game_id)||!SHA.test(m.source_file_sha256)||
    m.source_video_alignment_verified!==false||m.model_training_authorized!==false||
    m.commercial_reuse_authorized!==false||
    !['NONCANONICAL_FIXTURE_ONLY','PINNED_SOURCE_AND_PLAY_METADATA_VIDEO_PENDING'].includes(m.qualification_status)||
    typeof m.license_declaration!=='string'||!m.license_declaration.trim()||
    (licenseIdentifier!==null&&m.license_declaration!==licenseIdentifier)||
    !Array.isArray(m.plays)||m.plays.length<1||m.plays.length>12||
    m.play_count!==m.plays.length){
    throw new Error('Invalid local research manifest or unacknowledged source terms.');
  }
  if(expectedPlayCount!==null && m.plays.length!==expectedPlayCount)
    throw new Error('Manifest play count differs from expected research session size.');
  const listed=new Set();
  let total=mst.size;
  const results=[];
  for(const entry of m.plays){
    if(!entry||!PLAY.test(entry.play_id)||typeof entry.sha256!=='string'||
      !SHA.test(entry.sha256)||
      entry.file!==m.game_id+'-'+entry.play_id+'-research-replay.json'||
      listed.has(entry.file)||
      !Number.isSafeInteger(entry.recorded_frames)||entry.recorded_frames<1||
      !Number.isSafeInteger(entry.source_rows)||entry.source_rows<1)
      throw new Error('Unsafe, duplicate or malformed replay path in manifest.');
    listed.add(entry.file);
    const abs=path.join(root,entry.file);
    const stat=await lstat(abs);
    if(!stat.isFile()||stat.isSymbolicLink()||stat.size>MAX_FILE)
      throw new Error('Replay is missing, symlinked or oversized: '+entry.file);
    total+=stat.size;
    if(total>MAX_BATCH)
      throw new Error('Local research batch exceeds 50 MB import budget.');
    const h=createHash('sha256');
    for await (const chunk of createReadStream(abs))h.update(chunk);
    if(h.digest('hex').toLowerCase()!==entry.sha256.toLowerCase())
      throw new Error('Local replay SHA-256 mismatch: '+entry.file);
    results.push({play_id:entry.play_id,filename:entry.file,bytes:stat.size,
      recorded_frames:entry.recorded_frames,source_rows:entry.source_rows,
      sha256:entry.sha256});
  }
  for(const name of await readdir(root)){
    if(name.endsWith('.json')&&name!=='manifest.json'&&!listed.has(name))
      throw new Error('Unexpected extra research JSON: '+name);
  }
  return {
    source_kind:'USER_SUPPLIED_LOCAL_RESEARCH_SESSION',
    trust_boundary:'EXPORT_HASH_MATCH_ONLY_NOT_SOURCE_CSV_AUTHENTICATION',
    game_id:m.game_id,qualification_status:m.qualification_status,
    source_video_alignment_verified:false,model_training_authorized:false,
    commercial_reuse_authorized:false,
    play_count:results.length,manifest_file:manifestPath,
    replay_files:results.map(r=>path.join(root,r.filename)),plays:results,
    total_bytes:total,
  };
}
