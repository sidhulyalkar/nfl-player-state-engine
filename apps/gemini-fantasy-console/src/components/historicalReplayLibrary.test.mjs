import test from 'node:test';
import assert from 'node:assert/strict';
import { mergeReplayLibrary, replayKey, replayLabel, selectReplay, MAX_REPLAY_LIBRARY } from './historicalReplayLibrary.ts';

function replay(play_id, source='pinned source'){
  return {data_mode:'HISTORICAL_RESEARCH',tracking_fidelity:'RECORDED_FRAMES',
    game_id:'2017090700',play_id,frame_count:2,
    source,source_file_sha256:'a'.repeat(64),
    source_license_identifier:'test rights only',
    missing_frame_count:0,frame_coverage:1,play_direction:null,
    frames:[{frame_id:1,t_seconds_nominal:0,players:[],ball:null,events:[]},
      {frame_id:2,t_seconds_nominal:.1,players:[],ball:null,events:[]}]};
}
test('source file imports compose into a stable ordered playlist',()=>{
  const first=replay('938'),second=replay('2756');
  const lib=mergeReplayLibrary([],[first,second]);
  assert.deepEqual(lib.map(v=>v.play_id),['938','2756']);
  assert.equal(selectReplay(lib,replayKey(second)),second);
  assert.equal(selectReplay(lib,'bad'),null);
  assert.match(replayLabel(first),/938 .*2 recorded frames/);
  assert.notEqual(replayKey(first),replayKey(second));
});
test('idempotent exact duplicate import, no change to source coordinates',()=>{
  const first=replay('938');
  const initial=mergeReplayLibrary([],[first]);
  const result=mergeReplayLibrary(initial,[structuredClone(first)]);
  assert.equal(result.length,1);
  assert.equal(result[0],first);
});
test('conflicting same-game play cannot silently replace inspected evidence',()=>{
  const old=replay('938'),collision=replay('938','different source');
  assert.throws(()=>mergeReplayLibrary([old],[replay('2756'),collision]),/Conflicting data/);
  assert.equal(old.source,'pinned source');
});
test('cap rejected atomically even when additions include allowed play',()=>{
  const all=Array.from({length:MAX_REPLAY_LIBRARY},(_,i)=>replay(String(i)));
  assert.equal(mergeReplayLibrary([],all).length,MAX_REPLAY_LIBRARY);
  assert.throws(()=>mergeReplayLibrary(all,[replay('99')]),/at most/);
  const base=[replay('938')];
  assert.throws(()=>mergeReplayLibrary(base,Array.from({length:MAX_REPLAY_LIBRARY},(_,i)=>replay(String(i)))),/at most/);
  assert.equal(base.length,1);
});
test('game ID forms part of selection key and prevents cross-game collisions',()=>{
  const a=replay('938'),b=replay('938');
  b.game_id='2017090800';
  assert.equal(mergeReplayLibrary([],[a,b]).length,2);
  assert.notEqual(replayKey(a),replayKey(b));
});
