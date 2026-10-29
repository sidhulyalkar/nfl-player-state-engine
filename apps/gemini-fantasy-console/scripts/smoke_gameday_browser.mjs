#!/usr/bin/env node
/** Zero-dependency Chrome DevTools rendering smoke for built Fourth Down Lab. */
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {inspectPrivateResearchSession} from './privateResearchSession.mjs';
import { spawn } from 'node:child_process';
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { setTimeout as sleep } from 'node:timers/promises';

const url=process.env.PLAYLAB_PREVIEW_URL || 'http://127.0.0.1:4173/?workspace=gameday';
const artifacts=path.resolve('browser-artifacts');
const profile=await mkdtemp(path.join(os.tmpdir(),'pse-chrome-'));
await mkdir(artifacts,{recursive:true});
let browser,ws,id=0;
const pending=new Map();
function send(method,params={},sessionId) {
  return new Promise((resolve,reject)=>{
    const key=++id;
    const timer=setTimeout(()=>{pending.delete(key);reject(new Error('CDP timeout: '+method));},12000);
    pending.set(key,{
      resolve:value=>{clearTimeout(timer);resolve(value);},
      reject:error=>{clearTimeout(timer);reject(error);},
    });
    ws.send(JSON.stringify({id:key,method,params,...(sessionId?{sessionId}:{})}));
  });
}
async function evalPage(expression,sid) {
  const data=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true},sid);
  if(data.exceptionDetails)throw new Error('Chrome JavaScript error: '+JSON.stringify(data.exceptionDetails));
  return data.result?.value;
}
async function until(expression,sid,what) {
  for(let i=0;i<55;i++){
    const value=await evalPage(expression,sid);
    if(value)return value;
    await sleep(300);
  }
  throw new Error('Timed out awaiting '+what);
}
async function capture(sid,name) {
  const result=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:false},sid);
  await writeFile(path.join(artifacts,name),Buffer.from(result.data,'base64'));
}
try {
  browser=spawn(process.env.CHROME_BIN||'google-chrome',[
    '--headless=new','--no-sandbox','--disable-dev-shm-usage',
    '--no-first-run','--no-default-browser-check','--enable-unsafe-swiftshader',
    '--use-gl=angle','--use-angle=swiftshader','--remote-allow-origins=*',
    '--remote-debugging-port=0','--user-data-dir='+profile,'about:blank',
  ],{stdio:['ignore','ignore','pipe']});
  let stderr='';
  browser.stderr?.on('data',chunk=>{stderr=(stderr+String(chunk)).slice(-4000);});
  let port;
  // Allow slow GitHub runners up to 36 seconds to expose CDP; never silently skip.
  for(let i=0;i<300;i++){
    if(browser.exitCode!==null)throw new Error('Chrome exited before CDP startup: '+stderr);
    try {
      port=Number((await readFile(path.join(profile,'DevToolsActivePort'),'utf8')).split('\n')[0]);
      if(Number.isInteger(port)&&port>0)break;
    } catch { /* Browser writes port after startup. */ }
    await sleep(120);
  }
  if(!port)throw new Error('Chrome CDP startup timeout after 36s: exitCode='+browser.exitCode+'; stderr='+stderr);
  const version=await (await fetch('http://127.0.0.1:'+port+'/json/version')).json();
  ws=new WebSocket(version.webSocketDebuggerUrl);
  await new Promise((resolve,reject)=>{
    const timeout=setTimeout(()=>reject(new Error('Chrome WebSocket timeout')),10000);
    ws.addEventListener('open',()=>{clearTimeout(timeout);resolve();},{once:true});
    ws.addEventListener('error',()=>{clearTimeout(timeout);reject(new Error('Chrome WebSocket error'));},{once:true});
  });
  ws.addEventListener('message',event=>{
    const data=JSON.parse(event.data);
    const job=pending.get(data.id);
    if(!job)return;
    pending.delete(data.id);
    if(data.error)job.reject(new Error(JSON.stringify(data.error)));
    else job.resolve(data.result);
  });
  const target=await send('Target.createTarget',{url:'about:blank'});
  const {sessionId:sid}=await send('Target.attachToTarget',{targetId:target.targetId,flatten:true});
  await send('Runtime.enable',{},sid);
  await send('Page.enable',{},sid);
  await send('Emulation.setDeviceMetricsOverride',{width:1440,height:940,deviceScaleFactor:1,mobile:false},sid);
  await send('Page.navigate',{url},sid);
  await until("document.querySelector('.gameday-head h1')?.textContent?.includes('See the game beneath the game')",sid,'GameDay Lab');
  const state=await until("(()=>{const c=document.querySelector('.field3d-stage canvas:not(.field3d-labels)');if(!c?.width||!c?.height)return null;return {width:c.width,height:c.height,webgl:!!c.getContext('webgl2'),source:document.querySelector('.field3d-source')?.textContent||'',svg:!!document.querySelector('svg.gameday-field')}})()",sid,'native WebGL field');
  assert.equal(state.webgl,true,'WebGL2 context unavailable');
  assert.equal(state.svg,false,'Viewer unexpectedly rendered 2D SVG');
  assert.match(state.source,/ILLUSTRATIVE MOVEMENT/);
  assert.ok(state.width>=200&&state.height>=200);
  await capture(sid,'playlab-webgl3d.png');
  const click2D=await evalPage("(()=>{const b=[...document.querySelectorAll('.gameday-display-options button')].find(x=>x.textContent?.includes('2D Field'));b?.click();return !!b})()",sid);
  assert.equal(click2D,true);
  await until("!!document.querySelector('svg.gameday-field')&&!document.querySelector('.field3d-stage')",sid,'SVG fallback');
  await capture(sid,'playlab-svg2d.png');
  const click3D=await evalPage("(()=>{const b=[...document.querySelectorAll('.gameday-display-options button')].find(x=>x.textContent?.includes('3D Field'));b?.click();return !!b})()",sid);
  assert.equal(click3D,true);
  await until("!!document.querySelector('.field3d-stage canvas')",sid,'WebGL remount');
  // CI fixture is GENERATED, NOT an NFL observation. It exists solely to
  // exercise the file input, strict research schema, timeline and WebGL mount.
  const player=(id,side,x,y)=>({
    nfl_id:id,is_ball:false,team:side==='offense'?'away':'home',side,
    name:side==='offense'?'CI receiver':'CI defender',jersey:side==='offense'?'81':'24',
    x,y,z:null,speed_yards_per_s:null,acceleration_yards_per_s2:null,
    orientation_deg:null,movement_dir_deg:null,
  });
  const fixture={
    schema_version:1,data_mode:'HISTORICAL_RESEARCH',
    tracking_fidelity:'RECORDED_FRAMES',
    source:'CI GENERATED FIXTURE; NOT AN ACTUAL NFL PLAY',
    source_license_identifier:'internal-test-fixture-only',
    source_file_sha256:'c'.repeat(64),
    possession_team:'KC',
    source_play_metadata:{
      provenance:'NONCANONICAL_TEST_FIXTURE',season:2017,week:1,
      home_team:'NE',visitor_team:'KC',possession_team:'KC',offense_side:'away',
      quarter:1,down:3,yards_to_go:7,
      offense_formation_charted:'SHOTGUN',
      offense_personnel_charted:'1 RB, 2 TE, 2 WR',
    },
    position_quality:{
      policy:'omit_off_field_with_audit',
      omitted_missing_position_rows:0,omitted_off_field_position_rows:1,
      omitted_total_position_rows:1,affected_source_frame_ids:[5],
      never_clamped_or_interpolated:true,
    },
    game_id:'CI_TEST_GAME',play_id:'CI_TEST_PLAY',
    frame_count:3,missing_frame_count:2,frame_coverage:3/5,play_direction:null,
    frames:[
      {frame_id:1,t_seconds_nominal:0,events:['ball_snap'],players:[
        player('CI_WR','offense',55,23),player('CI_DB','defense',56,26),
      ],ball:null},
      {frame_id:2,t_seconds_nominal:.1,events:[],players:[
        player('CI_WR','offense',55.35,23.2),player('CI_DB','defense',56.1,26.1),
      ],ball:null},
      {frame_id:5,t_seconds_nominal:.4,events:[],players:[
        player('CI_WR','offense',59.1,26),player('CI_DB','defense',58.0,26),
      ],ball:null},
    ],
  };
  const fileAdded=await evalPage("(()=>{const input=document.querySelector('input[type=file][accept*=\"json\"]');if(!input)return false;const fixture="+JSON.stringify(fixture)+";const dt=new DataTransfer();dt.items.add(new File([JSON.stringify(fixture)],'ci-generated-tracking.json',{type:'application/json'}));input.files=dt.files;input.dispatchEvent(new Event('change',{bubbles:true}));return true})()",sid);
  assert.equal(fileAdded,true,'Historical replay file input missing');
  await until("document.querySelector('.gameday-head h1')?.textContent?.includes('Recorded movement, not reconstructed guesses')",sid,'historical replay UI');
  const researchSource=await until("document.querySelector('.field3d-source')?.textContent?.includes('RECORDED X/Y')",sid,'research mode source badge');
  assert.equal(researchSource,true);
  assert.equal(await evalPage("document.querySelector('.gameday-charted-meta')?.textContent?.includes('3 & 7')",sid),true,'Source-charted down and distance missing from historical view');
  assert.equal(await evalPage("document.querySelector('.gameday-charted-meta')?.textContent?.includes('SHOTGUN')",sid),true,'Source-charted formation missing from historical view');
  assert.equal(await evalPage("document.body.textContent?.includes('1 excluded')",sid),true,'Missing source exclusion audit in research interface');
  const resetResearch=await evalPage("(()=>{const b=document.querySelector('button[aria-label=\"Reset replay\"]');b?.click();return !!b})()",sid);
  assert.equal(resetResearch,true);
  await until("document.querySelector('.gameday-player-controls')?.textContent?.includes('frame 1')",sid,'first recorded frame');
  const stepResearch=await evalPage("(()=>{const b=document.querySelector('button[aria-label=\"Next recorded source frame\"]');b?.click();return !!b})()",sid);
  assert.equal(stepResearch,true);
  await until("document.querySelector('.gameday-player-controls')?.textContent?.includes('frame 2')",sid,'recorded second frame');
  await until("document.querySelector('.field3d-source')?.textContent?.includes('OBSERVED TRAVEL, NOT FACING')",sid,'measured travel provenance');
  await capture(sid,'playlab-ci-fixture-travel.png');
  const nextResearch=await evalPage("(()=>{document.querySelector('button[aria-label=\"Next recorded source frame\"]')?.click();return true})()",sid);
  assert.equal(nextResearch,true);
  await until("document.querySelector('.gameday-player-controls')?.textContent?.includes('frame 5')",sid,'source frame jump over missing IDs');
  assert.equal(await evalPage("document.querySelector('.gameday-history-meta')?.textContent?.includes('2 missing frames')",sid),true);

  // Session library: import a second synthetic replay and switch back without
  // re-upload, proving playback identity and full WebGL state reset.
  const anotherImported=await evalPage("(()=>{const input=document.querySelector('input[type=file][accept*=\"json\"]');if(!input)return false;const next={..."+JSON.stringify(fixture)+",play_id:'CI_NEXT_PLAY'};const dt=new DataTransfer();dt.items.add(new File([JSON.stringify(next)],'ci-next-play.json',{type:'application/json'}));input.files=dt.files;input.dispatchEvent(new Event('change',{bubbles:true}));return true})()",sid);
  assert.equal(anotherImported,true,'Add replay JSON control missing in historical viewer');
  await until("document.querySelector('.gameday-head')?.textContent?.includes('CI_NEXT_PLAY')",sid,'second research play loaded');
  assert.equal(await evalPage("document.querySelectorAll('select[aria-label=\"Select loaded historical play\"] option').length",sid),2,'Research play list should have two entries');
  // Two independently recorded play fields. Source snap events are required,
  // and both fields must be empty during an identical unrecorded frame window.
  const compareClicked=await evalPage("(()=>{const b=document.querySelector('button[aria-label=\\\"Compare recorded plays\\\"]');b?.click();return !!b})()",sid);
  assert.equal(compareClicked,true,'Two-play comparison navigation missing');
  await until("document.querySelector('main[aria-label=\\\"Two-play historical research comparison\\\"]')?.querySelectorAll('.gameday-compare-field').length===2",sid,'two observed overhead fields');
  assert.equal(await evalPage("document.querySelector('input[aria-label=\\\"Snap-relative comparison timeline\\\"]')!=null",sid),true);
  for(let step=1;step<=2;step++){
    const advanced=await evalPage("(()=>{const b=document.querySelector('button[aria-label=\\\"Step comparison forward one nominal frame\\\"]');b?.click();return !!b})()",sid);
    assert.equal(advanced,true);
    await until("document.querySelector('.gameday-compare-controls')?.textContent?.includes('Snap-relative '+("+step+"/10).toFixed(2)+'s')",sid,'comparison nominal step '+step);
  }
  assert.equal(await evalPage("document.querySelectorAll('.gameday-compare-field svg[aria-label*=\\\"source position unavailable\\\"]').length",sid),2,
    'Both plays must show a missing recorded source sample rather than holding a player position');
  await capture(sid,'playlab-synthetic-snap-comparison.png');
  const compareClosed=await evalPage("(()=>{const b=[...document.querySelectorAll('button')].find(b=>b.textContent?.includes('Back to replay'));b?.click();return !!b})()",sid);
  assert.equal(compareClosed,true);
  await until("document.querySelector('.gameday-head h1')?.textContent?.includes('Recorded movement, not reconstructed guesses')",sid,'return from compared replay');
  console.log('PASS: snap-relative twin-field rendering and missing-source-frame neutrality.');

  const switchedBack=await evalPage("(()=>{const selector=document.querySelector('select[aria-label=\"Select loaded historical play\"]');if(!selector)return false;selector.selectedIndex=0;selector.dispatchEvent(new Event('change',{bubbles:true}));return true})()",sid);
  assert.equal(switchedBack,true);
  await until("document.querySelector('.gameday-head')?.textContent?.includes('CI_TEST_PLAY')",sid,'switching to first recorded play');
  // Source frames advance immediately on a play switch. Pause and reset
  // before demanding the 0.0s first observation on shared CI runners.
  const resetAfterSwap=await evalPage("(()=>{const b=document.querySelector('button[aria-label=\"Reset replay\"]');b?.click();return !!b})()",sid);
  assert.equal(resetAfterSwap,true);
  await until("document.querySelector('.gameday-player-controls')?.textContent?.includes('frame 1')",sid,'switched replay reset control');
  const wentToDemo=await evalPage("(()=>{const b=[...document.querySelectorAll('button')].find(v=>v.textContent?.includes('Return to demo'));b?.click();return !!b})()",sid);
  assert.equal(wentToDemo,true);
  await until("document.querySelector('.gameday-head h1')?.textContent?.includes('See the game beneath the game')",sid,'demo reset');
  assert.equal(await evalPage("document.querySelectorAll('select[aria-label=\"Choose saved historical replay\"] option').length",sid),3,'Two plays remain in session on demo screen');
  const reopened=await evalPage("(()=>{const picker=document.querySelector('select[aria-label=\"Choose saved historical replay\"]');if(!picker)return false;picker.selectedIndex=2;picker.dispatchEvent(new Event('change',{bubbles:true}));return true})()",sid);
  assert.equal(reopened,true);
  await until("document.querySelector('.gameday-head')?.textContent?.includes('CI_NEXT_PLAY')",sid,'reopen saved play without file input');
  console.log('PASS: two synthetic recorded plays imported and switched in-memory without data replacement.');

  // Catalog is separate metadata-only user data. Confirm event search and
  // opening the exact matching play without fetching private positions.
  const backForCatalog=await evalPage("(()=>{const b=[...document.querySelectorAll('button')].find(v=>v.textContent?.includes('Return to demo'));b?.click();return !!b})()",sid);
  assert.equal(backForCatalog,true);
  await until("document.querySelector('.gameday-head h1')?.textContent?.includes('See the game beneath the game')",sid,'catalog demo view');
  const summaryPlay=(play_id,events)=>({
    game_id:'CI_TEST_GAME',play_id,source_rows:6,recorded_frames:3,
    missing_frame_ids:2,coverage_ratio:3/5,first_frame_id:1,last_frame_id:5,
    duration_seconds_nominal:.4,unique_players:2,max_players_per_frame:2,
    ball_recorded_frames:0,source_events:events,
    unrenderable_position_rows:1,off_field_rows:1,missing_xy_rows:0,
    affected_source_frame_ids:[5],
  });
  const catalog={
    schema_version:1,data_mode:'HISTORICAL_RESEARCH_METADATA_ONLY',
    game_id:'CI_TEST_GAME',source:'CI GENERATED METADATA; NOT NFL',
    source_sha256:'c'.repeat(64),source_bytes:1000,source_rows:12,
    play_count:2,positions_included:false,source_video_alignment_verified:false,
    plays:[summaryPlay('CI_TEST_PLAY',{ball_snap:[1]}),
      summaryPlay('CI_NEXT_PLAY',{touchdown:[5]})],
  };
  const catalogImported=await evalPage("(()=>{const inputs=[...document.querySelectorAll('input[type=file][accept*=\"json\"]')];const input=inputs[1];if(!input)return false;const metadata="+JSON.stringify(catalog)+";const dt=new DataTransfer();dt.items.add(new File([JSON.stringify(metadata)],'ci-catalog.json',{type:'application/json'}));input.files=dt.files;input.dispatchEvent(new Event('change',{bubbles:true}));return true})()",sid);
  assert.equal(catalogImported,true,'Metadata-only catalog file input missing');
  await until("document.querySelector('.gameday-catalog')?.textContent?.includes('Recorded game play atlas')",sid,'catalog UI');
  assert.equal(await evalPage("document.querySelectorAll('.gameday-catalog-play').length",sid),2,'catalog needs both tracked plays');
  const searched=await evalPage("(()=>{const input=document.querySelector('input[aria-label=\"Search recorded plays and events\"]');if(!input)return false;const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;setter.call(input,'touchdown');input.dispatchEvent(new Event('input',{bubbles:true}));return true})()",sid);
  assert.equal(searched,true,'Catalog event search missing');
  await until("document.querySelector('.gameday-catalog-count')?.textContent?.includes('1 source plays match')",sid,'filtered touchdown');
  assert.equal(await evalPage("document.querySelectorAll('.gameday-catalog-play').length",sid),1);
  const openedFromCatalog=await evalPage("(()=>{const b=[...document.querySelectorAll('.gameday-catalog-play button')].find(v=>v.textContent?.includes('Open recorded replay'));b?.click();return !!b})()",sid);
  assert.equal(openedFromCatalog,true);
  await until("document.querySelector('.gameday-head')?.textContent?.includes('CI_NEXT_PLAY')",sid,'catalog-selected actual session replay');
  console.log('PASS: position-free catalog imported, searched by recorded event, matching replay opened.');

  // Visual regression for observed proximity and quality provenance.
  const selectedObserved=await evalPage("(()=>{const select=document.querySelector('select[aria-label=\\\"Inspect tracked player\\\"]');if(!select)return false;select.value='CI_WR';select.dispatchEvent(new Event('change',{bubbles:true}));return true})()",sid);
  assert.equal(selectedObserved,true,'Historical player selection unavailable');
  await until("!!document.querySelector('section[aria-label=\\\"Observed nearest opponent separation\\\"] svg')",sid,'observed proximity visualization');
  assert.equal(await evalPage("document.querySelector('section[aria-label=\\\"Recorded frame evidence timeline\\\"]')?.textContent?.includes('Missing source frame IDs')",sid),true,'Evidence ribbon not mounted');
  assert.equal(await evalPage("document.querySelector('section[aria-label=\\\"Recorded frame evidence timeline\\\"]')?.textContent?.includes('Frames with excluded position rows')",sid),true,'Position exclusion not distinguished from frame gaps');
  await capture(sid,'playlab-ci-evidence-layers.png');
  console.log('PASS: selected-player proximity plot and source-quality ribbon rendered in Chromium.');

  // Synthetic manifest package: assert real browser Web Crypto import and
  // rejection of tampered bytes without overwriting the current session.
  const verifiedPlay={
    ...structuredClone(fixture),game_id:'2017090700',play_id:'938',rows:6,
  };
  const verifiedBytes=JSON.stringify(verifiedPlay);
  const verifiedName='2017090700-938-research-replay.json';
  const verifiedSha=createHash('sha256').update(verifiedBytes).digest('hex');
  const origin=(file,sha)=>({
    file,bytes:1024,sha256:sha,git_blob_sha1:'a'.repeat(40),identity_match:true,
  });
  const sessionManifest={
    schema_version:1,data_mode:'HISTORICAL_RESEARCH_BATCH_MANIFEST',
    qualification_status:'NONCANONICAL_FIXTURE_ONLY',
    game_id:'2017090700',source_file_sha256:'c'.repeat(64),
    source_identities:{
      tracking:origin('tracking_gameId_2017090700.csv','c'.repeat(64)),
      plays:origin('plays.csv','b'.repeat(64)),
      games:origin('games.csv','a'.repeat(64)),
    },
    source_video_alignment_verified:false,model_training_authorized:false,
    commercial_reuse_authorized:false,license_declaration:'internal-test-fixture-only',
    play_count:1,plays:[{
      play_id:'938',file:verifiedName,sha256:verifiedSha,source_rows:6,
      recorded_frames:3,missing_source_frames:2,omitted_position_rows:1,
      possession_team:'KC',metadata_provenance:'NONCANONICAL_TEST_FIXTURE',
    }],
  };
  const filesInBrowser=(replayBytes)=>"(()=>{const input=document.querySelector('input[type=file][accept*=\\\"json\\\"]');if(!input)return false;const dt=new DataTransfer();dt.items.add(new File(["+
    JSON.stringify(JSON.stringify(sessionManifest))+
    "],'manifest.json',{type:'application/json'}));dt.items.add(new File(["+
    JSON.stringify(replayBytes)+
    "],"+JSON.stringify(verifiedName)+",{type:'application/json'}));input.files=dt.files;input.dispatchEvent(new Event('change',{bubbles:true}));return true})()";
  assert.equal(await evalPage(filesInBrowser(verifiedBytes),sid),true,'Manifest importer unavailable');
  await until("document.querySelector('.gameday-head')?.textContent?.includes('2017090700')",sid,'manifest imported replay');
  assert.equal(await evalPage("document.querySelector('.gameday-history-meta')?.textContent?.includes('SHA-256 matches selected manifest')",sid),true,
    'Browser did not label verified package bytes');
  const beforeTamper=await evalPage("document.querySelectorAll('select[aria-label=\\\"Select loaded historical play\\\"] option').length",sid);
  assert.equal(beforeTamper,3,'Expected initial research session plus one verified fixture');
  assert.equal(await evalPage(filesInBrowser(verifiedBytes+' '),sid),true);
  await until("document.querySelector('[role=\\\"alert\\\"]')?.textContent?.includes('SHA-256 mismatch')",sid,'tampered manifest import rejection');
  assert.equal(await evalPage("document.querySelectorAll('select[aria-label=\\\"Select loaded historical play\\\"] option').length",sid),beforeTamper,
    'Tampered package modified research session library');
  console.log('PASS: browser SHA-256 manifest import and atomic tamper rejection.');



  console.log('PASS: real WebGL2 + 2D switch + synthetic CI replay import + recorded frame stepping + travel disclosure.');

  // AngleIQ is tested with synthetic local metadata/video bytes only.
  // No copyrighted NFL clips, source streams, or actual game findings.
  const angleReplay={...fixture,game_id:'2017090700',play_id:'938'};
  const addAngleReplay=await evalPage("(()=>{const input=document.querySelector('input[type=file][accept*=\\\"json\\\"]');if(!input)return false;const fixture="+JSON.stringify(angleReplay)+";const dt=new DataTransfer();dt.items.add(new File([JSON.stringify(fixture)],'ci-angle-research-replay.json',{type:'application/json'}));input.files=dt.files;input.dispatchEvent(new Event('change',{bubbles:true}));return true})()",sid);
  assert.equal(addAngleReplay,true,'AngleIQ fixture needs historical replay input');
  await until("document.querySelector('.gameday-head')?.textContent?.includes('2017090700')&&document.querySelector('.gameday-head')?.textContent?.includes('play 938')",sid,'synthetic numeric research identity');
  const angleiqOpened=await evalPage("(()=>{const b=document.querySelector('button[aria-label=\\\"Open AngleIQ multi-angle review\\\"]');b?.click();return !!b})()",sid);
  assert.equal(angleiqOpened,true,'AngleIQ entrypoint absent');
  await until("document.querySelector('main[aria-label=\\\"AngleIQ research video review\\\"]')!==null",sid,'AngleIQ view');
  const videoBytes='synthetic video bytes';
  const sourceHash=createHash('sha256').update(videoBytes).digest('hex');
  const angleManifest={
    schema_version:1,data_mode:'RIGHTS_DECLARED_VIDEO_RESEARCH',
    game_id:'2017090700',play_id:'938',tracking_source_sha256:'c'.repeat(64),
    rights:{declaration:'CI GENERATED VIDEO FIXTURE ONLY; NO THIRD-PARTY RIGHTS',
      local_playback_authorized:true,derivative_analysis_authorized:true,
      redistribution_authorized:false},
    events:[{id:'foot',event_time_s:.2,label:'Boundary review',question:'Can this view show ball and foot?',kind:'boundary_catch'}],
    angles:[
      {id:'sideline',name:'Synthetic sideline',kind:'sideline',
        source:{type:'local_file',filename:'synthetic-angle.mp4',sha256:sourceHash,bytes:21,duration_s:3},
        anchors:[{event_time_s:0,media_time_s:.4},{event_time_s:.3,media_time_s:.7}],
        evidence:[{event_id:'foot',provenance:'human_reviewed',ball:1,boundary:1,control:1,
          ground_contact:1,field_context:.1,clarity:.9,continuity:1,occlusion:0,note:'CI synthetic annotation'}]},
      {id:'external',name:'Example external reference',kind:'broadcast',
        source:{type:'external_link',url:'https://example.com/synthetic-external-viewer'},
        anchors:[],evidence:[]},
    ],
  };
  const manifestInBrowser=(value)=>"(()=>{const input=document.querySelector('input[aria-label=\\\"Import AngleIQ manifest\\\"]');if(!input)return false;const data="+JSON.stringify(value)+";const dt=new DataTransfer();dt.items.add(new File([JSON.stringify(data)],'ci-angleiq.json',{type:'application/json'}));input.files=dt.files;input.dispatchEvent(new Event('change',{bubbles:true}));return true})()";
  assert.equal(await evalPage(manifestInBrowser({...angleManifest,game_id:'2017090800'}),sid),true);
  await until("document.querySelector('[role=\\\"alert\\\"]')?.textContent?.includes('different game/play')",sid,'AngleIQ rejects wrong game');
  assert.equal(await evalPage(manifestInBrowser(angleManifest),sid),true);
  await until("document.querySelector('section[aria-label=\\\"AngleIQ camera rankings\\\"]')?.querySelectorAll('.angleiq-rank-list button').length===2",sid,'AngleIQ ranked camera list');
  assert.match(await evalPage("document.querySelector('.angleiq-rank-list button:first-child')?.textContent",sid),/Synthetic sideline/);
  assert.equal(await evalPage("document.querySelector('video.angleiq-video')===null",sid),true,'Unverified video should not render');
  const consent=await evalPage("(()=>{const box=document.querySelector('.angleiq-media-auth input[type=checkbox]');box?.click();return !!box})()",sid);
  assert.equal(consent,true);
  const selectAngleMedia=(payload)=>"(()=>{const input=document.querySelector('input[aria-label=\\\"Load authorized local camera videos\\\"]');if(!input)return false;const dt=new DataTransfer();dt.items.add(new File(["+JSON.stringify(payload)+"],'synthetic-angle.mp4',{type:'video/mp4'}));input.files=dt.files;input.dispatchEvent(new Event('change',{bubbles:true}));return true})()";
  assert.equal(await evalPage(selectAngleMedia('synthetic video bytex'),sid),true);
  await until("document.querySelector('[role=\\\"alert\\\"]')?.textContent?.includes('SHA-256 mismatch')",sid,'AngleIQ video digest rejection');
  assert.equal(await evalPage("document.querySelector('video.angleiq-video')===null",sid),true,'Corrupt media became playable');
  assert.equal(await evalPage(selectAngleMedia(videoBytes),sid),true);
  await until("document.querySelector('.angleiq-stage-footer')?.textContent?.includes('Selected bytes verified')",sid,'AngleIQ verified media');
  assert.equal(await evalPage("document.querySelector('video.angleiq-video')!==null",sid),true);
  await capture(sid,'playlab-angleiq-synthetic-review.png');
  const externalClicked=await evalPage("(()=>{const b=[...document.querySelectorAll('.angleiq-rank-list button')].find(b=>b.textContent?.includes('Example external reference'));b?.click();return !!b})()",sid);
  assert.equal(externalClicked,true);
  await until("document.querySelector('.angleiq-stage-footer a[href=\\\"https://example.com/synthetic-external-viewer\\\"]')!==null",sid,'external source link only');
  assert.equal(await evalPage("document.querySelector('video.angleiq-video')===null",sid),true,'External URLs must never be embedded as video');
  const exitedAngleIQ=await evalPage("(()=>{const b=[...document.querySelectorAll('button')].find(x=>x.textContent?.includes('Back to replay'));b?.click();return !!b})()",sid);
  assert.equal(exitedAngleIQ,true);
  await until("document.querySelector('.gameday-head h1')?.textContent?.includes('Recorded movement, not reconstructed guesses')",sid,'return from AngleIQ');
  console.log('PASS: AngleIQ identity, rights-confirmed local SHA, rankings and external-viewer boundary.');

  // Opt-in private, complete batch verification. CDP sets the *local* file
  // input directly: no HTTP upload, no serialized tracking bytes in messages,
  // no real-source screenshots, and no raw source included in output logs.
  if(process.env.PLAYLAB_REAL_SESSION_DIR){
    if(process.env.PLAYLAB_SOURCE_TERMS_ACKNOWLEDGED!=='yes' ||
      !process.env.PLAYLAB_SOURCE_LICENSE_ID)
      throw new Error('Local source-use terms must be explicitly reviewed and acknowledged.');
    const expected=Number(process.env.PLAYLAB_EXPECTED_PLAYS||'12');
    if(!Number.isSafeInteger(expected)||expected<1||expected>12)
      throw new Error('Expected local play count must be between 1 and 12.');
    const privateSession=await inspectPrivateResearchSession(
      process.env.PLAYLAB_REAL_SESSION_DIR,{
        expectedPlayCount:expected,
        licenseIdentifier:process.env.PLAYLAB_SOURCE_LICENSE_ID,
      },
    );
    // CI synthetic fixture already holds two play slots. The private batch
    // requires the full 12-slot quota, so reload to create a fresh isolated
    // browser-only research session before selecting any private source file.
    await send('Page.reload',{ignoreCache:true},sid);
    await until("document.querySelector('.gameday-head h1')?.textContent?.includes('See the game beneath the game')",sid,'isolated private import starting view');
    const existingPlayCount=0;
    const doc=await send('DOM.getDocument',{depth:1},sid);
    const query=await send('DOM.querySelector',{
      nodeId:doc.root.nodeId,
      selector:'.gameday-history-actions input[type=file][multiple]',
    },sid);
    assert.ok(query.nodeId,'Private research file input is missing');
    const started=performance.now();
    await send('DOM.setFileInputFiles',{
      files:[privateSession.manifest_file,...privateSession.replay_files],
      nodeId:query.nodeId,
    },sid);
    await evalPage("document.querySelector('.gameday-history-actions input[type=file][multiple]')?.dispatchEvent(new Event('change',{bubbles:true}))",sid);
    let complete=false;
    for(let attempt=0;attempt<180;attempt++){
      const result=await evalPage("(()=>({importing:document.querySelector('.gameday-history-actions')?.textContent?.includes('Importing'),historical:document.querySelector('.gameday-head h1')?.textContent?.includes('Recorded movement, not reconstructed guesses'),verified:document.querySelector('.gameday-history-meta')?.textContent?.includes('SHA-256 matches selected manifest'),options:document.querySelectorAll('select[aria-label=\\\"Select loaded historical play\\\"] option').length,error:document.querySelector('[role=\\\"alert\\\"]')?.textContent||null}))()",sid);
      if(result?.error)throw new Error('Local manifest import failed: '+result.error);
      if(result?.historical&&result.verified&&result.options>=privateSession.play_count+existingPlayCount){
        complete=true;break;
      }
      await sleep(500);
    }
    assert.equal(complete,true,'Private session did not become available in Chromium');
    const importElapsed=performance.now()-started;
    const loadedOptions=await evalPage("Array.from(document.querySelectorAll('select[aria-label=\\\"Select loaded historical play\\\"] option')).map(o=>o.value)",sid);
    const expectedKeys=privateSession.plays.map(play=>
      JSON.stringify([privateSession.game_id,play.play_id]));
    for(const key of expectedKeys)
      assert.ok(loadedOptions.includes(key),'Missing locally imported replay '+key);
    let slowestSwitch=0;
    for(const [index,play] of privateSession.plays.entries()){
      const key=expectedKeys[index];
      const renderStarted=performance.now();
      const selected=await evalPage("(()=>{const input=document.querySelector('select[aria-label=\\\"Select loaded historical play\\\"]');if(!input)return false;input.value="+JSON.stringify(key)+";input.dispatchEvent(new Event('change',{bubbles:true}));return true})()",sid);
      assert.equal(selected,true,'Cannot select research replay '+play.play_id);
      await until("(()=>{const h=document.querySelector('.gameday-head p')?.textContent||'';const verified=document.querySelector('.gameday-history-meta')?.textContent||'';return h.includes('play '+"+JSON.stringify(play.play_id)+")&&verified.includes('SHA-256 matches selected manifest')&&!!document.querySelector('section[aria-label=\\\"Recorded frame evidence timeline\\\"]')})()",sid,'qualified replay '+play.play_id);
      slowestSwitch=Math.max(slowestSwitch,performance.now()-renderStarted);
    }
    const elapsed=performance.now()-started;
    const browserMemory=await evalPage("performance.memory?.usedJSHeapSize??null",sid);
    const redacted={
      qualification:'LOCAL_BROWSER_RESEARCH_SESSION',
      status:'PASS_BROWSER_FILE_AND_MANIFEST_CONSISTENCY_ONLY',
      play_count:privateSession.play_count,
      full_replay_render_count:privateSession.play_count,
      slowest_replay_switch_ms:Math.round(slowestSwitch),
      total_bytes:privateSession.total_bytes,
      import_wall_ms:Math.round(importElapsed),
      entire_session_navigation_wall_ms:Math.round(elapsed),
      browser_used_js_heap_bytes:browserMemory,
      source_video_alignment_verified:false,
      model_training_authorized:false,
      commercial_reuse_authorized:false,
      note:'Original source-byte authorization and film alignment are separate gates.',
    };
    if(process.env.PLAYLAB_LOCAL_REPORT_PATH){
      const target=path.resolve(process.env.PLAYLAB_LOCAL_REPORT_PATH);
      await writeFile(target,JSON.stringify(redacted,null,2)+'\\n',{flag:'wx',mode:0o600});
    }
    console.log('PASS: PRIVATE browser session: '+JSON.stringify(redacted));
  }

  // Optional local source-data check. Never exercised by push/PR CI:
  // PLAYLAB_REAL_REPLAY_PATH must be a user-authorized local research file.
  // No raw source rows or screenshots of this sample are published.
  if (process.env.PLAYLAB_REAL_REPLAY_PATH) {
    const privatePath=path.resolve(process.env.PLAYLAB_REAL_REPLAY_PATH);
    const realContent=await readFile(privatePath,'utf8');
    if (Buffer.byteLength(realContent,'utf8')>25_000_000)throw new Error('Local real replay exceeds 25 MB safety limit');
    const record=JSON.parse(realContent);
    assert.equal(record.data_mode,'HISTORICAL_RESEARCH');
    assert.equal(record.tracking_fidelity,'RECORDED_FRAMES');
    assert.ok(record.frame_count>=2 && Array.isArray(record.frames));
    const wentBack=await evalPage("(()=>{const b=[...document.querySelectorAll('button')].find(v=>v.textContent?.includes('Return to demo'));b?.click();return !!b})()",sid);
    assert.equal(wentBack,true,'Cannot leave synthetic replay');
    await until("document.querySelector('.gameday-head h1')?.textContent?.includes('See the game beneath the game')",sid,'return to tutorial mode');
    const imported=await evalPage("(()=>{const input=document.querySelector('input[type=file][accept*=\"json\"]');if(!input)return false;const dt=new DataTransfer();dt.items.add(new File(["+JSON.stringify(realContent)+"],'local-research-replay.json',{type:'application/json'}));input.files=dt.files;input.dispatchEvent(new Event('change',{bubbles:true}));return true})()",sid);
    assert.equal(imported,true,'Local research file input unavailable');
    await until("document.querySelector('.gameday-head h1')?.textContent?.includes('Recorded movement, not reconstructed guesses')",sid,'real source replay mount');
    const meta=await evalPage("document.querySelector('.gameday-head')?.textContent",sid);
    assert.ok(meta?.includes(record.game_id) && meta?.includes(record.play_id),'Incorrect real replay identity shown');
    await until("document.querySelector('.field3d-source')?.textContent?.includes('RECORDED X/Y')",sid,'real recorded field');
    const first=record.frames[0].frame_id,next=record.frames[1].frame_id;
    await evalPage("document.querySelector('button[aria-label=\"Reset replay\"]')?.click()",sid);
    await until("document.querySelector('.gameday-player-controls')?.textContent?.includes('frame "+first+"')",sid,'real first source frame');
    await evalPage("document.querySelector('button[aria-label=\"Next recorded source frame\"]')?.click()",sid);
    await until("document.querySelector('.gameday-player-controls')?.textContent?.includes('frame "+next+"')",sid,'real second recorded frame');
    console.log('PASS: locally provided real-source replay loaded and stepped without raw-data output. Video alignment remains pending.');
  }


} finally {
  for(const job of pending.values())job.reject(new Error('Browser shutdown'));
  pending.clear();
  ws?.close();
  if(browser?.exitCode===null)browser.kill('SIGTERM');
  await sleep(500);
  await rm(profile,{recursive:true,force:true,maxRetries:6,retryDelay:250});
}
