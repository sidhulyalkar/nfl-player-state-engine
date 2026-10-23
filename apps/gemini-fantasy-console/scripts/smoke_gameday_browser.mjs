#!/usr/bin/env node
/** Zero-dependency Chrome DevTools rendering smoke for built Fourth Down Lab. */
import assert from 'node:assert/strict';
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
  for(let i=0;i<100;i++){
    if(browser.exitCode!==null)throw new Error('Chrome exited: '+stderr);
    try {
      port=Number((await readFile(path.join(profile,'DevToolsActivePort'),'utf8')).split('\n')[0]);
      if(Number.isInteger(port)&&port>0)break;
    } catch { /* Browser writes port after startup. */ }
    await sleep(120);
  }
  if(!port)throw new Error('Chrome debugging port unavailable: '+stderr);
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
  const switchedBack=await evalPage("(()=>{const selector=document.querySelector('select[aria-label=\"Select loaded historical play\"]');if(!selector)return false;selector.selectedIndex=0;selector.dispatchEvent(new Event('change',{bubbles:true}));return true})()",sid);
  assert.equal(switchedBack,true);
  await until("document.querySelector('.gameday-head')?.textContent?.includes('CI_TEST_PLAY')",sid,'switching to first recorded play');
  await until("document.querySelector('.gameday-player-controls')?.textContent?.includes('frame 1')",sid,'switched replay timeline reset');
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


  console.log('PASS: real WebGL2 + 2D switch + synthetic CI replay import + recorded frame stepping + travel disclosure.');

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
