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
  console.log('PASS: WebGL2 stage + provenance label + 2D fallback + 3D remount');
} finally {
  for(const job of pending.values())job.reject(new Error('Browser shutdown'));
  pending.clear();
  ws?.close();
  if(browser?.exitCode===null)browser.kill('SIGTERM');
  await sleep(500);
  await rm(profile,{recursive:true,force:true,maxRetries:6,retryDelay:250});
}
