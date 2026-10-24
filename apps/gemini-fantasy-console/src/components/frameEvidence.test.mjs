import test from 'node:test';
import assert from 'node:assert/strict';
import {buildFrameEvidenceOverview} from './frameEvidence.ts';

const frame=(id,ball=null)=>({frame_id:id,t_seconds_nominal:(id-1)/10,players:[],ball,events:[]});
test('separately counts source gaps, position exclusions, and unrecorded ball frames',()=>{
  const replay={
    frames:[frame(1,{x:40,y:20}),frame(2),frame(5,{x:42,y:20}),frame(6)],
    position_quality:{affected_source_frame_ids:[2,5]},
  };
  const result=buildFrameEvidenceOverview(replay,6);
  assert.equal(result.recorded_frames,4);
  assert.equal(result.missing_source_frames,2);
  assert.equal(result.frames_with_excluded_positions,2);
  assert.equal(result.frames_without_recorded_ball,2);
  assert.deepEqual(result.bins.map(bin=>bin.status),[
    'recorded','position-excluded','source-gap','source-gap',
    'position-excluded','ball-unobserved',
  ]);
});
test('binning preserves totals without creating one DOM segment per missing source frame',()=>{
  const replay={frames:[frame(1),frame(200001)],position_quality:{affected_source_frame_ids:[200001]}};
  const result=buildFrameEvidenceOverview(replay,80);
  assert.equal(result.bins.length,80);
  assert.equal(result.bins.reduce((n,b)=>n+b.recorded_frames,0),2);
  assert.equal(result.bins.reduce((n,b)=>n+b.missing_source_frames,0),199999);
  assert.equal(result.frames_with_excluded_positions,1);
});
test('all observed positions and ball samples are clean when gap free',()=>{
  const p={x:40,y:20};
  const o=buildFrameEvidenceOverview({frames:[frame(4,p),frame(5,p),frame(6,p)]});
  assert.equal(o.missing_source_frames,0);
  assert.equal(o.frames_without_recorded_ball,0);
  assert.equal(o.frames_with_excluded_positions,0);
  assert.ok(o.bins.every(b=>b.status==='recorded'));
});
test('absurd source span and invalid bin request are rejected',()=>{
  const x={frames:[frame(1),frame(250002)]};
  assert.throws(()=>buildFrameEvidenceOverview(x),/unreasonably large/);
  assert.throws(()=>buildFrameEvidenceOverview({frames:[frame(1)]},251),/valid resolution/);
});
