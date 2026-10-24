import test from 'node:test';
import assert from 'node:assert/strict';
import {nearestOpponentSamples,consecutiveSeparationSegments,nearestOpponentSummary} from './observedSeparation.ts';
const p=(id,side,x,y)=>({nfl_id:id,side,x,y,is_ball:false});
const f=(frame_id,players)=>({frame_id,t_seconds_nominal:(frame_id-1)*.1,players,ball:null,events:[]});
test('only source-declared opposing side contributes to geometric separation',()=>{
 const frames=[f(1,[p('WR','offense',40,10),p('CB','defense',43,14),p('LB','defense',50,10),p('TE','offense',40,11)])];
 const s=nearestOpponentSamples(frames,'WR');
 assert.equal(s[0].distance_yards,5);
 assert.equal(s[0].opponent_id,'CB');
});
test('missing player, side or opponents are unavailable rather than estimated',()=>{
 const frames=[f(1,[p('WR','offense',1,1)]),f(2,[p('CB','defense',3,1)]),
   f(3,[p('WR',null,2,1),p('CB','defense',3,1)])];
 assert.deepEqual(nearestOpponentSamples(frames,'WR').map(s=>s.distance_yards),[null,null,null]);
 assert.equal(nearestOpponentSummary(nearestOpponentSamples(frames,'WR')).closest_yards,null);
});
test('source frame discontinuities and unavailable observations break lines',()=>{
 const frames=[f(1,[p('WR','offense',40,10),p('CB','defense',43,10)]),
 f(2,[p('WR','offense',41,10),p('CB','defense',43,10)]),
 f(4,[p('WR','offense',42,10),p('CB','defense',43,10)]),
 f(5,[p('WR','offense',42,10)]),
 f(6,[p('WR','offense',42,10),p('CB','defense',43,10)])];
 const samples=nearestOpponentSamples(frames,'WR');
 assert.deepEqual(samples.map(s=>s.distance_yards),[3,2,1,null,1]);
 assert.deepEqual(consecutiveSeparationSegments(samples).map(s=>s.map(p=>p.frame_id)),[[1,2],[4],[6]]);
 assert.deepEqual(nearestOpponentSummary(samples),{observed_frames:4,closest_yards:1,farthest_yards:3});
});
test('different nearest opponents may change without implying an assignment',()=>{
 const frames=[f(1,[p('WR','offense',40,10),p('CB1','defense',41,10),p('CB2','defense',44,10)]),
 f(2,[p('WR','offense',42,10),p('CB1','defense',40,10),p('CB2','defense',42.5,10)])];
 const s=nearestOpponentSamples(frames,'WR');
 assert.deepEqual(s.map(x=>x.opponent_id),['CB1','CB2']);
 assert.deepEqual(s.map(x=>x.distance_yards),[1,.5]);
});
