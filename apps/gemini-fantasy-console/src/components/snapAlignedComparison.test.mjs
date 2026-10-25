import test from 'node:test';
import assert from 'node:assert/strict';
import {snapAlignedComparison,observedAtRelativeTime,compareObservedPlayer,comparisonUnavailableMessage} from './snapAlignedComparison.ts';

const player=(id,side,x,y=20)=>({nfl_id:id,side,x,y});
const frame=(id,t,players,events=[])=>({frame_id:id,t_seconds_nominal:t,players,ball:null,events});
function replay(id,frames,source='a'.repeat(64),game='2017090700'){
  return {game_id:game,play_id:id,source_file_sha256:source,frames};
}
const left=replay('938',[
  frame(1,0,[player('WR','offense',30),player('CB','defense',33)]),
  frame(2,.1,[player('WR','offense',31),player('CB','defense',34)],['ball_snap']),
  frame(3,.2,[player('WR','offense',34),player('CB','defense',36)]),
  frame(6,.5,[player('WR','offense',40),player('CB','defense',42)]),
]);
const right=replay('2756',[
  frame(10,0,[player('RB','offense',20),player('LB','defense',23)],['ball_snap']),
  frame(11,.1,[player('RB','offense',21),player('LB','defense',24)]),
  frame(13,.3,[player('RB','offense',25),player('LB','defense',30)]),
]);

test('source-recorded snap offsets produce a shared window without resampling',()=>{
  const a=snapAlignedComparison(left,right);
  assert.equal(a.available,true);
  assert.equal(a.left_snap_frame_id,2);
  assert.equal(a.right_snap_frame_id,10);
  assert.ok(Math.abs(a.min_relative_seconds)<1e-8);
  assert.equal(a.max_relative_seconds,.3);
});
test('missing snap, source collision, different game, same play fail closed',()=>{
  const noSnap=replay('55',[frame(1,0,[]),frame(2,.1,[])]);
  assert.equal(snapAlignedComparison(left,noSnap).reason,'missing-snap');
  assert.equal(snapAlignedComparison(left,replay('5',right.frames,'b'.repeat(64))).reason,'different-source');
  assert.equal(snapAlignedComparison(left,replay('5',right.frames,'a'.repeat(64),'2017091000')).reason,'different-source');
  assert.equal(snapAlignedComparison(left,left).reason,'same-play');
  assert.match(comparisonUnavailableMessage('missing-snap'),/no alignment is estimated/);
});
test('unrecorded frame remains an empty field, never last known geometry',()=>{
  const gap=observedAtRelativeTime(left,.2);
  assert.equal(gap.is_gap,true);
  assert.equal(gap.frame,null);
  assert.equal(gap.source_frame_id,3);
  const measured=observedAtRelativeTime(right,.3);
  assert.equal(measured.is_gap,false);
  assert.equal(measured.source_frame_id,13);
  assert.throws(()=>observedAtRelativeTime(right,Number.NaN),/finite/);
});
test('selected players are independent and geometry only comes from present frames',()=>{
  const a=compareObservedPlayer(left,.1,'WR');
  assert.equal(a.frame_id,3);
  assert.equal(a.distance_from_snap_yards,3);
  assert.equal(a.nearest_recorded_opponent_yards,2);
  const b=compareObservedPlayer(right,.1,'RB');
  assert.equal(b.frame_id,11);
  assert.equal(b.distance_from_snap_yards,1);
  assert.equal(b.nearest_recorded_opponent_yards,3);
  const gone=compareObservedPlayer(left,.2,'WR');
  assert.equal(gone.geometry_available,false);
  assert.equal(gone.nearest_recorded_opponent_yards,null);
  const missing=compareObservedPlayer(right,.1,'WR');
  assert.equal(missing.geometry_available,false);
});
test('window intersection is empty when snap events occupy disjoint nominal domains',()=>{
  const r=replay('500',[
    frame(1,0,[player('WR','offense',30)]),
    frame(2,.1,[player('WR','offense',30)]),
    frame(3,.2,[player('WR','offense',30)],['ball_snap']),
  ]);
  const l=replay('501',[
    frame(10,0,[player('WR','offense',30)],['ball_snap']),
  ]);
  assert.equal(snapAlignedComparison(r,l).reason,'no-overlap');
});
