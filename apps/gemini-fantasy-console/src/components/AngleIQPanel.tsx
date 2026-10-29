import {useEffect,useMemo,useRef,useState, type ChangeEvent} from 'react';
import {ArrowLeft,Camera,FileVideo,ShieldCheck,ShieldAlert,PlayCircle,ExternalLink,ScanEye,Clock3} from 'lucide-react';
import {
  ANGLEIQ_MAX_MANIFEST_BYTES,parseAngleIQManifest,verifyLocalAngleMedia,
  rankAngleIQ,complementaryAngleIQ,mediaTimeAtEvent,eventTimeAtMedia,
  type AngleIQManifest,type CameraAngle,type ViewObjective,
} from './angleIQ';

function formatTime(t:number|null){return t===null?'Not synchronized':t.toFixed(2)+'s';}
function readableScore(x:number|null){
  return x===null?'Unranked':Math.round(x*100)+'/100';
}
export function AngleIQPanel({gameId,playId,onBack}:{
  gameId:string;playId:string;onBack:()=>void;
}){
  const [manifest,setManifest]=useState<AngleIQManifest|null>(null);
  const [manifestError,setManifestError]=useState<string|null>(null);
  const [fileError,setFileError]=useState<string|null>(null);
  const [importing,setImporting]=useState(false);
  const [rightsConfirmed,setRightsConfirmed]=useState(false);
  const [media,setMedia]=useState<Map<string,File>>(()=>new Map());
  const [eventId,setEventId]=useState<string>('');
  const [activeAngleId,setActiveAngleId]=useState('');
  const [objective,setObjective]=useState<ViewObjective>('evidence');
  const [playEventTime,setPlayEventTime]=useState<number|null>(null);
  const timeRef=useRef<number|null>(null);
  const videoRef=useRef<HTMLVideoElement|null>(null);
  const [videoUrls,setVideoUrls]=useState<Map<string,string>>(()=>new Map());
  useEffect(()=>{
    const urls=new Map<string,string>();
    for(const [id,file] of media)urls.set(id,URL.createObjectURL(file));
    setVideoUrls(urls);
    return ()=>{for(const url of urls.values())URL.revokeObjectURL(url);};
  },[media]);
  const event=useMemo(()=>manifest?.events.find(e=>e.id===eventId)??null,[manifest,eventId]);
  const angle=useMemo(()=>manifest?.angles.find(a=>a.id===activeAngleId)??null,[manifest,activeAngleId]);
  const ranked=useMemo(()=>manifest&&event?rankAngleIQ(manifest,event.id,objective):[],[manifest,event,objective]);
  const bestViews=useMemo(()=>manifest&&event?complementaryAngleIQ(manifest,event.id,objective):[],[manifest,event,objective]);
  const canPlay=Boolean(angle&&angle.source.type==='local_file'&&media.has(angle.id)&&videoUrls.has(angle.id));
  const localSource=angle?.source.type==='local_file'?angle.source:null;
  const seekableAt=angle&&event?mediaTimeAtEvent(angle,playEventTime??event.event_time_s):null;
  useEffect(()=>{
    if(!angle||!videoRef.current||!canPlay)return;
    const target=mediaTimeAtEvent(angle,timeRef.current??event?.event_time_s??Number.NaN);
    const player=videoRef.current;
    if(target!==null){
      // Video metadata might arrive later; the loadedmetadata handler repeats this.
      try {player.currentTime=target;} catch {/* Browser will retry once metadata arrives. */}
    }
  },[angle,canPlay,videoUrls,eventId,event?.event_time_s]);
  function onSelectEvent(nextId:string){
    if(!manifest)return;
    const e=manifest.events.find(v=>v.id===nextId);
    if(!e)return;
    setEventId(nextId);timeRef.current=e.event_time_s;setPlayEventTime(e.event_time_s);
  }
  function onSelectAngle(nextId:string){
    setActiveAngleId(nextId);
  }
  async function onManifestFile(e:ChangeEvent<HTMLInputElement>){
    const f=e.currentTarget.files?.[0];e.currentTarget.value='';
    if(!f)return;
    setManifestError(null);setFileError(null);
    try{
      if(f.size>ANGLEIQ_MAX_MANIFEST_BYTES)throw new Error('AngleIQ manifest exceeds 250 KB.');
      const parsed=parseAngleIQManifest(JSON.parse(await f.text()) as unknown);
      if(parsed.game_id!==gameId||parsed.play_id!==playId)
        throw new Error('Video manifest belongs to a different game/play; choose the matching replay.');
      // Replace the complete source session atomically rather than borrowing files
      // or rights declarations from a previous imported source.
      setMedia(new Map());setRightsConfirmed(false);setManifest(parsed);
      setEventId(parsed.events[0].id);
      setActiveAngleId(parsed.angles[0].id);
      timeRef.current=parsed.events[0].event_time_s;
      setPlayEventTime(parsed.events[0].event_time_s);
    }catch(error){setManifestError(error instanceof Error?error.message:'Invalid AngleIQ manifest');}
  }
  async function onMediaFiles(e:ChangeEvent<HTMLInputElement>){
    const files=Array.from(e.currentTarget.files??[]);e.currentTarget.value='';
    if(!manifest||!files.length||importing)return;
    if(!rightsConfirmed){setFileError('Confirm that your local-video processing is authorized first.');return;}
    setImporting(true);setFileError(null);
    try{
      const verified=await verifyLocalAngleMedia(manifest,files);
      // No partial installation of corrupted or incorrectly declared media.
      setMedia(verified);
    }catch(error){setFileError(error instanceof Error?error.message:'Could not validate local media');}
    finally{setImporting(false);}
  }
  const seekCurrentVideo=()=>{
    if(!videoRef.current||!angle)return;
    const destination=mediaTimeAtEvent(angle,timeRef.current??event?.event_time_s??Number.NaN);
    if(destination!==null)videoRef.current.currentTime=destination;
  };
  const updateVideoClock=()=>{
    if(!videoRef.current||!angle)return;
    const t=eventTimeAtMedia(angle,videoRef.current.currentTime);
    if(t!==null){timeRef.current=t;setPlayEventTime(t);}
  };
  return <main className="gameday-page angleiq-page" aria-label="AngleIQ research video review">
    <header className="gameday-head">
      <div><div className="gameday-kicker"><Camera size={16}/> FOURTH DOWN LAB / ANGLEIQ</div>
        <h1>The best view depends on the question.</h1>
        <p>Game {gameId} · play {playId} · rights-declared, local-first multi-angle research</p>
      </div>
      <div className="gameday-history-actions"><button type="button" onClick={onBack}><ArrowLeft size={15}/> Back to replay</button></div>
    </header>
    <div className="angleiq-legal" role="note"><ShieldAlert size={18}/>
      <span>No NFL feeds, stream extraction, automatic downloading, or redistributed video.
      Official clips can be linked externally; local playback requires your permission
      declaration and a matching video digest. These checks do not verify legal ownership.</span>
    </div>
    <section className="gameday-panel angleiq-import" aria-label="AngleIQ source manifest">
      <label className="angleiq-file-action"><FileVideo size={16}/>
        Import play-angle manifest (.json)
        <input aria-label="Import AngleIQ manifest" type="file" accept=".json,application/json" onChange={onManifestFile}/>
      </label>
      <p className="gameday-muted">Bring a locally authored AngleIQ v1 manifest matching this historical game and play.
        Camera evidence and media synchronization anchors must be explicitly supplied; the viewer never infers them from tracking.</p>
      {manifestError&&<p className="gameday-import-error" role="alert">{manifestError}</p>}
      {manifest&&<div className="angleiq-source-metadata">
        <ShieldCheck size={17}/>
        <div><strong>{manifest.angles.length} declared angle(s) · {manifest.events.length} event question(s)</strong>
          <p>{manifest.rights.declaration}</p>
          <small>Declared source rights only · redistribution unauthorized · browser local evidence</small>
        </div>
      </div>}
      {manifest&&<div className="angleiq-media-auth">
        <label><input type="checkbox" checked={rightsConfirmed} onChange={e=>setRightsConfirmed(e.target.checked)}
          disabled={!manifest.rights.local_playback_authorized||!manifest.rights.derivative_analysis_authorized}/>
          I have reviewed the source terms and am authorized to process these local video files.</label>
        <label className={'angleiq-file-action'+(!rightsConfirmed?' disabled':'')}>
          {importing?'Checking SHA-256…':'Select local video files (optional)'}
          <input type="file" aria-label="Load authorized local camera videos"
            multiple accept=".mp4,.webm,video/mp4,video/webm"
            disabled={!rightsConfirmed||importing} onChange={onMediaFiles}/>
        </label>
        <small>Up to 8 cameras, 40 MB/file and 160 MB total per selection. Files remain in your browser and are not uploaded.</small>
        {fileError&&<p className="gameday-import-error" role="alert">{fileError}</p>}
      </div>}
    </section>
    {manifest&&event&&<div className="angleiq-workspace">
      <div className="angleiq-controls">
        <label>Review question
          <select aria-label="AngleIQ review question" value={eventId} onChange={e=>onSelectEvent(e.target.value)}>
            {manifest.events.map(e=><option value={e.id} key={e.id}>{e.label}: {e.question}</option>)}
          </select>
        </label>
        <label>Ranking purpose
          <select aria-label="AngleIQ ranking purpose" value={objective}
            onChange={e=>setObjective(e.target.value as ViewObjective)}>
            <option value="evidence">Evidence visibility</option>
            <option value="cinematic">Highlight storytelling</option>
          </select>
        </label>
      </div>
      <div className="angleiq-stage-grid">
        <section className="gameday-panel angleiq-stage" aria-label="AngleIQ featured view">
          <div className="angleiq-stage-header"><div><strong>{angle?.name??'No angle selected'}</strong>
            <small>{angle?.kind.replaceAll('_',' ')??''}</small></div>
            <span><Clock3 size={14}/> Play clock {formatTime(playEventTime)}</span>
          </div>
          {canPlay&&angle?<video key={angle.id+':'+videoUrls.get(angle.id)} ref={videoRef}
            className="angleiq-video" src={videoUrls.get(angle.id)}
            aria-label={'Authorized local '+angle.name+' recording'} controls playsInline preload="metadata"
            onLoadedMetadata={seekCurrentVideo} onTimeUpdate={updateVideoClock} onSeeked={updateVideoClock}
          />:<div className="angleiq-video-empty">
            <PlayCircle size={34}/>
            <strong>{angle?.source.type==='external_link'?'Official or permitted viewer link':'No locally verified video loaded'}</strong>
            <small>{angle?.source.type==='external_link'
              ?'Open the source site for playback. External content is not copied into Play Lab.'
              :'Load the declared video bytes to see this angle here. No sample NFL video is bundled.'}</small>
          </div>}
          <div className="angleiq-stage-footer">
            {angle?.source.type==='external_link'&&<a href={angle.source.url} target="_blank" rel="noreferrer noopener">
              <ExternalLink size={14}/> Open source viewing page</a>}
            {localSource&&<span><ShieldCheck size={14}/> {media.has(angle!.id)?'Selected bytes verified against declared SHA-256':'Video bytes not checked'}</span>}
            <span>{seekableAt===null?'Video/event synchronization unqualified':
              'Normal-speed alignment between declared anchors'}</span>
          </div>
          <div className="angleiq-timeline">
            <strong>Decision moments</strong>
            <div className="angleiq-events">
              {manifest.events.map(e=><button type="button" key={e.id}
                className={e.id===eventId?'active':''} onClick={()=>onSelectEvent(e.id)}>
                {e.label}<small>{e.event_time_s.toFixed(2)}s</small></button>)}
            </div>
          </div>
        </section>
        <aside className="gameday-panel angleiq-ranked" aria-label="AngleIQ camera rankings">
          <div className="gameday-aside-heading"><div><ScanEye size={17}/><h2>Angles for this question</h2></div></div>
          <p>{event.question}</p>
          <div className="angleiq-rank-list">
            {ranked.map((r,index)=><button type="button" key={r.camera_id}
              className={r.camera_id===activeAngleId?'selected':''}
              onClick={()=>onSelectAngle(r.camera_id)}>
              <span className="angleiq-rank-num">{index+1}</span>
              <div><strong>{r.name}</strong>
                <small>{r.kind.replaceAll('_',' ')} · observed dimensions {Math.round(r.coverage*100)}%</small>
                <small>{r.reason}</small></div>
              <span className="angleiq-rank-score">{readableScore(r.score)}</span>
            </button>)}
          </div>
          <p className="gameday-muted">Ranks are heuristic camera-visibility scores based on user-supplied reviewed annotations, not verified rulings, NFL grades or legal findings.</p>
          <div className="angleiq-evidence-set"><strong>Complementary views</strong>
            <p>{bestViews.length?bestViews.map(a=>a.name).join(' + '):
              'Insufficient reviewed evidence for a defensible recommended set.'}</p>
            <small>The second and third view prefer different camera kinds; they do not add factual certainty automatically.</small>
          </div>
        </aside>
      </div>
    </div>}
    {!manifest&&<section className="gameday-panel angleiq-empty-intro"><h2>Start with permitted footage</h2>
      <p>AngleIQ indexes camera references and evidence questions first. For a licensed
        recording, add local video filenames, exact SHA-256 hashes, two independently checked
        normal-speed alignment anchors, and visibility annotations. Otherwise link to an
        official viewing page and leave unverified camera evidence unranked.</p>
    </section>}
    <footer className="gameday-footer">ANGLEIQ RESEARCH ONLY · VIDEO RIGHTS USER-DECLARED · OUTCOMES NEVER AUTOMATICALLY DETERMINED</footer>
  </main>;
}
