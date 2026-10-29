import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash,webcrypto} from 'node:crypto';
import {
  parseAngleIQManifest,mediaTimeAtEvent,eventTimeAtMedia,
  rankAngleIQ,complementaryAngleIQ,verifyLocalAngleMedia,
} from './angleIQ.ts';

const sha=createHash('sha256').update('synthetic video bytes').digest('hex');
const good={
  schema_version:1,data_mode:'RIGHTS_DECLARED_VIDEO_RESEARCH',
  game_id:'2017090700',play_id:'938',tracking_source_sha256:'c'.repeat(64),
  rights:{declaration:'Synthetic generated fixture: no third-party NFL footage',
    local_playback_authorized:true,derivative_analysis_authorized:true,
    redistribution_authorized:false},
  events:[
    {id:'catch',event_time_s:1.4,label:'Landing',question:'Is the receiver in bounds?',kind:'boundary_catch'},
    {id:'setup',event_time_s:.5,label:'Setup',question:'What is the route spacing?',kind:'route_context'},
  ],
  angles:[
    {id:'sideline',name:'Sideline close-up',kind:'sideline',
      source:{type:'local_file',filename:'synthetic-angle.mp4',sha256:sha,bytes:21,duration_s:3},
      anchors:[{event_time_s:0,media_time_s:.4},{event_time_s:2,media_time_s:2.4}],
      evidence:[
        {event_id:'catch',provenance:'human_reviewed',ball:1,boundary:1,control:.9,
          ground_contact:1,field_context:.2,clarity:.9,continuity:.9,occlusion:.1,note:'Foot and boundary visible'},
      ],
    },
    {id:'broadcast',name:'TV broadcast',kind:'broadcast',
      source:{type:'external_link',url:'https://www.nfl.com/videos/example-view'},
      anchors:[],evidence:[
        {event_id:'catch',provenance:'human_reviewed',ball:.8,boundary:.1,control:.5,
          ground_contact:.2,field_context:1,clarity:.95,continuity:1,occlusion:.1,note:null},
      ],
    },
  ],
};
const copy=()=>structuredClone(good);

test('versioned research manifest and original source declarations are parsed',()=>{
  const m=parseAngleIQManifest(copy());
  assert.equal(m.game_id,'2017090700');
  assert.equal(m.rights.redistribution_authorized,false);
  assert.equal(m.angles.length,2);
});
test('reject source identity, duplicate source paths and unsafe external links',()=>{
  for(const bad of [
    m=>{m.game_id='fake';},m=>{m.tracking_source_sha256='wrong';},m=>{m.angles[1].id='sideline';},
    m=>{m.angles[1].source.url='javascript:alert(1)';},
    m=>{m.angles[1].source.url='http://localhost:8000/media';},
    m=>{m.angles[0].source.filename='../secret.mp4';},
    m=>{m.angles[0].source.sha256='wrong';},
    m=>{m.angles[0].source.bytes=40_000_001;},
    m=>{m.rights.redistribution_authorized=true;},
    m=>{m.events[1].id='catch';},
    m=>{m.angles[0].anchors[1].media_time_s=3;},
    m=>{m.angles[0].anchors[1].media_time_s=1.0;},
    m=>{m.angles[0].evidence[0].ball=1.4;},
  ]){
    const v=copy();bad(v);
    assert.throws(()=>parseAngleIQManifest(v),/AngleIQ manifest/);
  }
});
test('two manual normal-speed anchors support bounded mapping; no single-anchor guesses',()=>{
  const a=parseAngleIQManifest(copy()).angles[0];
  assert.ok(Math.abs(mediaTimeAtEvent(a,1.4)-1.8)<1e-6);
  assert.ok(Math.abs(eventTimeAtMedia(a,1.8)-1.4)<1e-6);
  assert.equal(mediaTimeAtEvent(a,3),null);
  assert.equal(eventTimeAtMedia(a,0),null);
  const one=structuredClone(a);one.anchors.length=1;
  assert.equal(mediaTimeAtEvent(one,0),null);
  assert.equal(eventTimeAtMedia(one,.4),null);
});
test('evidence ranks actual human annotations, not an outcome ruling',()=>{
  const m=parseAngleIQManifest(copy());
  const rank=rankAngleIQ(m,'catch');
  assert.equal(rank[0].camera_id,'sideline');
  assert.ok(rank[0].score>rank[1].score);
  assert.match(rank[0].reason,/no play outcome inferred/);
  assert.deepEqual(complementaryAngleIQ(m,'catch').map(v=>v.camera_id),['sideline','broadcast']);
  assert.ok(rankAngleIQ(m,'catch','cinematic')[0].score!==null);
  assert.throws(()=>rankAngleIQ(m,'missing'),/Unknown/);
});
test('unreviewed or sparse claims cannot receive a reassuring numeric grade',()=>{
  const m=copy();
  m.angles[0].evidence[0].provenance='unvalidated_model';
  let result=rankAngleIQ(parseAngleIQManifest(m),'catch');
  assert.equal(result.find(v=>v.camera_id==='sideline').score,null);
  m.angles[0].evidence[0].provenance='human_reviewed';
  m.angles[0].evidence[0].boundary=null;
  m.angles[0].evidence[0].ball=null;
  m.angles[0].evidence[0].control=null;
  result=rankAngleIQ(parseAngleIQManifest(m),'catch');
  assert.equal(result.find(v=>v.camera_id==='sideline').score,null);
  assert.equal(complementaryAngleIQ(parseAngleIQManifest(m),'setup').length,0);
});
test('exact local bytes selected by user, tampered bytes fail atomically',async()=>{
  if(!globalThis.crypto)globalThis.crypto=webcrypto;
  const m=parseAngleIQManifest(copy());
  const bytes=new TextEncoder().encode('synthetic video bytes');
  const file=new File([bytes],'synthetic-angle.mp4',{type:'video/mp4'});
  assert.equal(file.size,21);
  const checked=await verifyLocalAngleMedia(m,[file]);
  assert.equal(checked.get('sideline'),file);
  await assert.rejects(verifyLocalAngleMedia(m,[new File(['synthetic video bytex'],
    'synthetic-angle.mp4',{type:'video/mp4'})]),/SHA-256 mismatch/);
  await assert.rejects(verifyLocalAngleMedia(m,[new File([bytes],
    'unknown.mp4',{type:'video/mp4'})]),/Unknown or duplicate/);
  const denied=copy();denied.rights.derivative_analysis_authorized=false;
  await assert.rejects(verifyLocalAngleMedia(parseAngleIQManifest(denied),[file]),/not authorized/);
});
