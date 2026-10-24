import test from 'node:test';
import assert from 'node:assert/strict';
import {recordedCameraCue,syntheticCameraCue,smoothOrbitTarget} from './playCameraDirector.ts';

const players=[{nfl_id:'WR',x:40,y:10},{nfl_id:'CB',x:45,y:10}];
test('recorded ball anchors camera without guessing a target receiver',()=>{
  const cue=recordedCameraCue({frame_id:7,events:['pass_forward'],ball:{x:50,y:24},players},false,'WR');
  assert.deepEqual(cue.target,[-10,0,-2.6499999999999986]);
  assert.equal(cue.evidence,'RECORDED_BALL');
  assert.equal(cue.distance,83);
});
test('ball absent uses explicitly selected recorded player, then observed centroid',()=>{
  const frame={frame_id:1,events:[],ball:null,players};
  assert.equal(recordedCameraCue(frame,false,'WR').evidence,'RECORDED_PLAYER');
  const cue=recordedCameraCue(frame,false);
  assert.equal(cue.evidence,'OBSERVED_GROUP');
  assert.equal(cue.target[0],-17.5);
});
test('unknown gap or no observed positions freezes camera',()=>{
  const frame={frame_id:1,events:['touchdown'],ball:null,players};
  assert.equal(recordedCameraCue(frame,true),null);
  assert.equal(recordedCameraCue({...frame,players:[]},false),null);
  assert.equal(recordedCameraCue({...frame,ball:{x:NaN,y:0},players:[]},false),null);
});
test('source events only change framing, never create missing ball coordinates',()=>{
  const frame={frame_id:13,events:['touchdown'],ball:null,players};
  const cue=recordedCameraCue(frame,false);
  assert.equal(cue.distance,75);
  assert.equal(cue.evidence,'OBSERVED_GROUP');
});
test('ease preserves time-step stability and never overshoots',()=>{
  const target=[20,0,10],start=[0,0,0];
  const at=smoothOrbitTarget(start,target,.016);
  assert.ok(at[0]>0&&at[0]<20);
  assert.ok(at[2]>0&&at[2]<10);
  assert.deepEqual(smoothOrbitTarget(start,target,0),start);
  assert.ok(smoothOrbitTarget(start,target,10)[0]<20);
});
test('synthetic camera keeps explicit provenance and field bounds',()=>{
  assert.equal(syntheticCameraCue({x:30,y:17},'live').distance,83);
  assert.equal(syntheticCameraCue({x:-1,y:17},'live'),null);
});
