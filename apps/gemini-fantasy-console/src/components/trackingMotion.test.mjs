import test from 'node:test';
import assert from 'node:assert/strict';
import { motionAtFrame, observedDistance } from './trackingMotion.ts';

const frames = [
  { frame_id: 1, t_seconds_nominal: 0, players: [
    { nfl_id: '11', x: 40, y: 10 },
    { nfl_id: '22', x: 42, y: 10 },
  ] },
  { frame_id: 2, t_seconds_nominal: .1, players: [
    { nfl_id: '11', x: 40.3, y: 10.4 },
    { nfl_id: '22', x: 42, y: 10 },
  ] },
  { frame_id: 4, t_seconds_nominal: .3, players: [
    { nfl_id: '11', x: 49, y: 22 },
    { nfl_id: '33', x: 44, y: 12 },
  ] },
  { frame_id: 5, t_seconds_nominal: .4, players: [
    { nfl_id: '11', x: 49, y: 23 },
    { nfl_id: '33', x: 44, y: 12 },
  ] },
];

test('speed is measured from consecutive 10Hz frame deltas in yards/s',()=>{
  const m=motionAtFrame(frames,1);
  const p=m.find(x=>x.nfl_id==='11');
  assert.ok(p);
  assert.ok(Math.abs(p.displacement_yards-.5)<1e-9);
  assert.ok(Math.abs(p.computed_speed_yards_per_second-5)<1e-9);
  assert.equal(m.find(x=>x.nfl_id==='22')?.computed_speed_yards_per_second,0);
});
test('no fabricated motion through frame 3 gap, or before the first frame',()=>{
  assert.equal(motionAtFrame(frames,0).length,0);
  assert.equal(motionAtFrame(frames,2).length,0);
  assert.equal(motionAtFrame(frames,99).length,0);
  assert.ok(Math.abs(motionAtFrame(frames,3)[0].displacement_yards-1)<1e-9);
});
test('observed path length is a lower bound when frames are missing',()=>{
  const m=observedDistance(frames,'11',3);
  assert.ok(Math.abs(m.yards-1.5)<1e-9);
  assert.equal(m.observed_pairs,2);
  assert.equal(m.complete,false);
});
test('no velocity from invalid or inconsistent source timestamps',()=>{
  const wrong=[
    {frame_id:1,t_seconds_nominal:0,players:[{nfl_id:'1',x:10,y:10}]},
    {frame_id:2,t_seconds_nominal:9,players:[{nfl_id:'1',x:11,y:10}]},
  ];
  assert.deepEqual(motionAtFrame(wrong,1),[]);
  wrong[1].t_seconds_nominal=.1;
  wrong[1].players=[{nfl_id:'1',x:Infinity,y:10}];
  assert.deepEqual(motionAtFrame(wrong,1),[]);
});
test('identity gaps never cause implicit tracking joins',()=>{
  const a=[{frame_id:1,t_seconds_nominal:0,players:[{nfl_id:'1',x:10,y:10}]}];
  const b={frame_id:2,t_seconds_nominal:.1,players:[{nfl_id:'2',x:11,y:10}]};
  assert.deepEqual(motionAtFrame([...a,b],1),[]);
});
