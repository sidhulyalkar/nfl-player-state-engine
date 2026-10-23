import test from 'node:test';
import assert from 'node:assert/strict';
import { frameAtTime, stepFrame, displayClock } from './trackingTimeline.ts';

const frames=[
  {frame_id:1,t_seconds_nominal:0},
  {frame_id:2,t_seconds_nominal:.1},
  {frame_id:5,t_seconds_nominal:.4},
  {frame_id:6,t_seconds_nominal:.5},
];
test('uses only observed source frame ids and marks gaps explicitly',()=>{
  assert.deepEqual(frameAtTime(frames,0).index,0);
  assert.equal(frameAtTime(frames,.09).is_gap,false);
  assert.equal(frameAtTime(frames,.1).source_frame_id,2);
  assert.equal(frameAtTime(frames,.19).is_gap,false);
  assert.equal(frameAtTime(frames,.2).is_gap,true);
  assert.equal(frameAtTime(frames,.3).source_frame_id,2);
  assert.equal(frameAtTime(frames,.39).is_gap,true);
  assert.equal(frameAtTime(frames,.4).is_gap,false);
  assert.equal(frameAtTime(frames,.5).source_frame_id,6);
});
test('frame stepping skips unrecorded frames instead of synthesizing them',()=>{
  const next=stepFrame(frames,1,1);
  assert.deepEqual(next,{index:2,frame_id:5,time:.4,skipped_source_frames:2});
  const prev=stepFrame(frames,2,-1);
  assert.deepEqual(prev,{index:1,frame_id:2,time:.1,skipped_source_frames:2});
  assert.equal(stepFrame(frames,0,-1).frame_id,1);
  assert.equal(stepFrame(frames,3,1).frame_id,6);
});
test('empty source, bad time and bad rate fail closed',()=>{
  assert.throws(()=>frameAtTime([],0),/Invalid source/);
  assert.throws(()=>frameAtTime(frames,Number.NaN),/Invalid source/);
  assert.throws(()=>frameAtTime(frames,0,0),/Invalid source/);
  assert.throws(()=>stepFrame([],0,1),/Invalid frame/);
});
test('exposes accurate subframe playback clock',()=>{
  assert.equal(displayClock(.43),'0.43s');
  assert.equal(displayClock(Infinity),'—');
});
