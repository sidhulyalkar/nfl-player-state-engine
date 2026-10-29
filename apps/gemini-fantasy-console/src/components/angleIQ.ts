/** AngleIQ v1: user-supplied, rights-declared multi-angle metadata.
 * No video scraping, undocumented source feeds, automatic calls or model-grade
 * tactical assertions. All observations are explicitly human declared.
 */
export type AngleQuestion='boundary_catch'|'goal_line'|'possession'|'route_context'|'general';
export type CameraKind='broadcast'|'sideline'|'end_zone'|'goal_line'|'other';
export type EvidenceDimension='ball'|'boundary'|'control'|'ground_contact'|'field_context'|'clarity'|'continuity'|'occlusion';
export type ViewObjective='evidence'|'cinematic';
export interface AngleAnchor {event_time_s:number;media_time_s:number;}
export interface AngleEvent {
  id:string;event_time_s:number;label:string;question:string;kind:AngleQuestion;
}
export interface RightsDeclaration {
  declaration:string;
  local_playback_authorized:boolean;
  derivative_analysis_authorized:boolean;
  redistribution_authorized:false;
}
export interface AngleEvidence {
  event_id:string;
  provenance:'human_reviewed'|'unvalidated_model';
  ball:number|null;boundary:number|null;control:number|null;
  ground_contact:number|null;field_context:number|null;
  clarity:number|null;continuity:number|null;occlusion:number|null;
  note:string|null;
}
export type MediaSource =
  | {type:'local_file';filename:string;sha256:string;bytes:number;duration_s:number}
  | {type:'external_link';url:string};
export interface CameraAngle {
  id:string;name:string;kind:CameraKind;
  source:MediaSource;anchors:AngleAnchor[];
  evidence:AngleEvidence[];
}
export interface AngleIQManifest {
  schema_version:1;
  data_mode:'RIGHTS_DECLARED_VIDEO_RESEARCH';
  game_id:string;play_id:string;tracking_source_sha256:string;
  rights:RightsDeclaration;
  events:AngleEvent[];angles:CameraAngle[];
}
export const ANGLEIQ_MAX_MANIFEST_BYTES=250_000;
export const ANGLEIQ_MAX_VIDEO_BYTES=40_000_000;
export const ANGLEIQ_MAX_SELECTED_BYTES=160_000_000;
const ID=/^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/;
const SAFE_FILE=/^[A-Za-z0-9][A-Za-z0-9_. -]{0,127}\.(mp4|webm)$/i;
const SHA=/^[a-fA-F0-9]{64}$/;
const kinds:AngleQuestion[]=['boundary_catch','goal_line','possession','route_context','general'];
const cameras:CameraKind[]=['broadcast','sideline','end_zone','goal_line','other'];
const dimensions:EvidenceDimension[]=['ball','boundary','control','ground_contact','field_context','clarity','continuity','occlusion'];
const validString=(s:unknown,max=160):s is string=>typeof s==='string'&&s.trim().length>0&&s.length<=max;
const validSeconds=(x:unknown,limit=3600):x is number=>typeof x==='number'&&Number.isFinite(x)&&x>=0&&x<=limit;
const number01=(x:unknown):boolean=>x===null||(typeof x==='number'&&Number.isFinite(x)&&x>=0&&x<=1);
function safeHttps(url:unknown):boolean{
  if(typeof url!=='string'||url.length>2048)return false;
  try {
    const u=new URL(url);
    return u.protocol==='https:'&&!u.username&&!u.password&&!!u.hostname&&
      !/^(localhost|127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|\[?::1\]?)/i.test(u.hostname);
  }catch{return false;}
}
function assert(condition:unknown,message:string):asserts condition{
  if(!condition)throw new Error('AngleIQ manifest: '+message);
}
export function parseAngleIQManifest(input:unknown):AngleIQManifest{
  assert(!!input&&typeof input==='object'&&!Array.isArray(input),'expected an object');
  const m=input as AngleIQManifest;
  assert(m.schema_version===1&&m.data_mode==='RIGHTS_DECLARED_VIDEO_RESEARCH','unsupported version or data mode');
  assert(typeof m.game_id==='string'&&/^\d{10}$/.test(m.game_id),'invalid official game ID');
  assert(typeof m.play_id==='string'&&/^\d{1,10}$/.test(m.play_id),'invalid play ID');
  assert(typeof m.tracking_source_sha256==='string'&&SHA.test(m.tracking_source_sha256),'invalid tracking source SHA-256');
  const r=m.rights;
  assert(!!r&&validString(r.declaration,250)&&
    typeof r.local_playback_authorized==='boolean'&&
    typeof r.derivative_analysis_authorized==='boolean'&&
    r.redistribution_authorized===false,'explicit conservative rights declaration required');
  assert(Array.isArray(m.events)&&m.events.length>=1&&m.events.length<=24,'1-24 source-declared event questions required');
  assert(Array.isArray(m.angles)&&m.angles.length>=1&&m.angles.length<=8,'1-8 angles required');
  const eventIds=new Set<string>();
  for(const e of m.events){
    assert(!!e&&ID.test(e.id)&&!eventIds.has(e.id)&&
      validSeconds(e.event_time_s,300)&&validString(e.label,100)&&
      validString(e.question,240)&&kinds.includes(e.kind),'invalid/duplicate event');
    eventIds.add(e.id);
  }
  const angleIds=new Set<string>(), filenames=new Set<string>();
  for(const a of m.angles){
    assert(!!a&&ID.test(a.id)&&!angleIds.has(a.id)&&validString(a.name,80)&&
      cameras.includes(a.kind),'invalid/duplicate angle');
    angleIds.add(a.id);
    const s=a.source;
    assert(!!s&&['local_file','external_link'].includes(s.type),'unsupported media source');
    if(s.type==='local_file'){
      assert(SAFE_FILE.test(s.filename)&&!filenames.has(s.filename.toLowerCase())&&SHA.test(s.sha256)&&
        Number.isSafeInteger(s.bytes)&&s.bytes>0&&s.bytes<=ANGLEIQ_MAX_VIDEO_BYTES&&
        validSeconds(s.duration_s)&&s.duration_s>0,'invalid local video identity or size');
      filenames.add(s.filename.toLowerCase());
    }else{
      assert(safeHttps(s.url),'external references must be public HTTPS links');
    }
    assert(Array.isArray(a.anchors)&&a.anchors.length<=16,'invalid synchronization anchors');
    for(let i=0;i<a.anchors.length;i++){
      const an=a.anchors[i];
      assert(!!an&&validSeconds(an.event_time_s,300)&&validSeconds(an.media_time_s)&&
        (s.type!=='local_file'||an.media_time_s<=s.duration_s),'invalid source anchor');
      if(i>0){
        const prev=a.anchors[i-1];
        assert(an.event_time_s>prev.event_time_s&&an.media_time_s>prev.media_time_s,
          'anchors must be strictly increasing');
        const sourceDelta=an.event_time_s-prev.event_time_s;
        const videoDelta=an.media_time_s-prev.media_time_s;
        assert(Math.abs(sourceDelta-videoDelta)<=0.2,
          'normal-speed anchor drift exceeds 200 ms; slow-motion is not synchronized');
      }
    }
    assert(Array.isArray(a.evidence)&&a.evidence.length<=m.events.length,'invalid angle observations');
    const seen=new Set<string>();
    for(const ev of a.evidence){
      assert(!!ev&&eventIds.has(ev.event_id)&&!seen.has(ev.event_id)&&
        ['human_reviewed','unvalidated_model'].includes(ev.provenance)&&
        dimensions.every(k=>number01(ev[k]))&&
        (ev.note===null||validString(ev.note,360)),'invalid or duplicate evidence annotation');
      seen.add(ev.event_id);
    }
  }
  return m;
}
/** Two distinct normal-speed source anchors are necessary for timeline sync.
 * Returns null rather than pretending that one cue uniquely aligns clocks.
 */
export function mediaTimeAtEvent(angle:CameraAngle,eventSeconds:number):number|null{
  if(!Number.isFinite(eventSeconds)||angle.source.type!=='local_file'||angle.anchors.length<2)return null;
  const anchors=angle.anchors;
  if(eventSeconds<anchors[0].event_time_s||eventSeconds>anchors[anchors.length-1].event_time_s)return null;
  for(let i=1;i<anchors.length;i++){
    if(eventSeconds<=anchors[i].event_time_s){
      const a=anchors[i-1],b=anchors[i];
      const ratio=(eventSeconds-a.event_time_s)/(b.event_time_s-a.event_time_s);
      const t=a.media_time_s+ratio*(b.media_time_s-a.media_time_s);
      return t<=angle.source.duration_s?t:null;
    }
  }
  return null;
}
export function eventTimeAtMedia(angle:CameraAngle,videoSeconds:number):number|null{
  if(!Number.isFinite(videoSeconds)||angle.source.type!=='local_file'||angle.anchors.length<2)return null;
  const anchors=angle.anchors;
  if(videoSeconds<anchors[0].media_time_s||videoSeconds>anchors[anchors.length-1].media_time_s)return null;
  for(let i=1;i<anchors.length;i++){
    if(videoSeconds<=anchors[i].media_time_s){
      const a=anchors[i-1],b=anchors[i];
      return a.event_time_s+(videoSeconds-a.media_time_s)/
        (b.media_time_s-a.media_time_s)*(b.event_time_s-a.event_time_s);
    }
  }
  return null;
}
export interface AngleRank {
  camera_id:string;name:string;kind:CameraKind;score:number|null;coverage:number;
  provenance:'human_reviewed'|'unrated';reason:string;
}
const EVIDENCE_WEIGHTS:Record<AngleQuestion,Partial<Record<EvidenceDimension,number>>>={
  boundary_catch:{ball:2,boundary:3,control:2,ground_contact:2,clarity:1,continuity:1,occlusion:-2},
  goal_line:{ball:3,boundary:3,ground_contact:2,clarity:1,continuity:2,occlusion:-2},
  possession:{ball:3,control:3,ground_contact:2,clarity:1,continuity:2,occlusion:-2},
  route_context:{field_context:4,ball:1,clarity:1,continuity:2,occlusion:-1},
  general:{ball:2,field_context:2,clarity:2,continuity:2,occlusion:-1},
};
const CINEMATIC:Partial<Record<EvidenceDimension,number>>={
  ball:1,field_context:2,clarity:3,continuity:3,occlusion:-2,
};
export function rankAngleIQ(manifest:AngleIQManifest,eventId:string,objective:ViewObjective='evidence'):AngleRank[]{
  const event=manifest.events.find(e=>e.id===eventId);
  if(!event)throw new Error('Unknown AngleIQ event');
  const weights=objective==='cinematic'?CINEMATIC:EVIDENCE_WEIGHTS[event.kind];
  const total=Object.values(weights).reduce((sum,w)=>sum+Math.abs(w??0),0);
  return manifest.angles.map(angle=>{
    const annotation=angle.evidence.find(e=>e.event_id===eventId&&e.provenance==='human_reviewed');
    if(!annotation)return {camera_id:angle.id,name:angle.name,kind:angle.kind,
      score:null,coverage:0,provenance:'unrated' as const,
      reason:'No human-reviewed visibility annotation for this question'};
    let observed=0,weighted=0;
    for(const [key,rawWeight] of Object.entries(weights) as [EvidenceDimension,number][]){
      const value=annotation[key];
      if(value===null)continue;
      const mag=Math.abs(rawWeight);
      observed+=mag;
      weighted+=mag*(rawWeight<0?1-value:value);
    }
    const coverage=observed/total;
    return {camera_id:angle.id,name:angle.name,kind:angle.kind,
      // Missing dimensions count as unknown, not positive evidence.
      score:coverage>=0.6?weighted/total:null,coverage,
      provenance:'human_reviewed' as const,
      reason:coverage<0.6?'Insufficient observed dimensions for a defensible ranking':
        'Heuristic visibility ranking from human annotations; no play outcome inferred'};
  }).sort((a,b)=>(b.score??-1)-(a.score??-1)||b.coverage-a.coverage||
    a.camera_id.localeCompare(b.camera_id));
}
export function complementaryAngleIQ(manifest:AngleIQManifest,eventId:string,objective:ViewObjective='evidence',count=3):AngleRank[]{
  const ranked=rankAngleIQ(manifest,eventId,objective).filter(r=>r.score!==null);
  if(!ranked.length)return [];
  const result=[ranked[0]];
  while(result.length<Math.min(count,ranked.length)){
    const candidates=ranked.filter(r=>!result.some(x=>x.camera_id===r.camera_id));
    candidates.sort((a,b)=>(
      ((b.score??0)+(!result.some(x=>x.kind===b.kind)?0.07:0))-
      ((a.score??0)+(!result.some(x=>x.kind===a.kind)?0.07:0))
    )||a.camera_id.localeCompare(b.camera_id));
    result.push(candidates[0]);
  }
  return result;
}
/** Browser-only exact media matching; no network access or user-video upload.
 * A digest match establishes identity against the user-declared manifest only.
 */
export async function verifyLocalAngleMedia(manifest:AngleIQManifest,files:readonly File[]):Promise<Map<string,File>>{
  if(files.length>manifest.angles.length)throw new Error('Too many selected local media files.');
  if(files.reduce((sum,f)=>sum+f.size,0)>ANGLEIQ_MAX_SELECTED_BYTES)
    throw new Error('Selected media exceed the 160 MB browser safety budget.');
  const expected=new Map(manifest.angles.filter(a=>a.source.type==='local_file')
    .map(a=>[(a.source as Extract<MediaSource,{type:'local_file'}>).filename.toLowerCase(),a]));
  const result=new Map<string,File>(),names=new Set<string>();
  for(const file of files){
    const name=file.name.toLowerCase();
    const angle=expected.get(name);
    if(!angle||names.has(name))throw new Error('Unknown or duplicate video file: '+file.name);
    if(!manifest.rights.local_playback_authorized||!manifest.rights.derivative_analysis_authorized)
      throw new Error('Local processing was not authorized by the supplied rights declaration.');
    const source=angle.source as Extract<MediaSource,{type:'local_file'}>;
    if(file.size!==source.bytes||file.size>ANGLEIQ_MAX_VIDEO_BYTES)
      throw new Error('Selected video size differs from declared source bytes.');
    if(!/^video\/(mp4|webm)$/.test(file.type)&&file.type!=='')
      throw new Error('Unsupported browser video MIME type.');
    const digest=await crypto.subtle.digest('SHA-256',await file.arrayBuffer());
    const hash=Array.from(new Uint8Array(digest),b=>b.toString(16).padStart(2,'0')).join('');
    if(hash!==source.sha256.toLowerCase())throw new Error('Video SHA-256 mismatch: '+file.name);
    result.set(angle.id,file);names.add(name);
  }
  return result;
}
