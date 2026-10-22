import test from 'node:test';
import assert from 'node:assert/strict';
import { parseHistoricalReplay } from './historicalReplaySchema.ts';

function valid() {
  return {
    data_mode:'HISTORICAL_RESEARCH',
    tracking_fidelity:'RECORDED_FRAMES',
    game_id:'2017090700',
    play_id:'2756',
    source:'NFL published historical tracking',
    source_license_identifier:'reviewed-source-terms',
    source_file_sha256:'a'.repeat(64),
    frame_count:2,
    frame_coverage:1,
    frames:[
      {frame_id:1,t_seconds_nominal:0,events:['ball_snap'],players:[
        {nfl_id:'11',is_ball:false,x:40,y:12,speed_yards_per_s:2.5,acceleration_yards_per_s2:null},
      ],ball:null},
      {frame_id:2,t_seconds_nominal:.1,events:[],players:[
        {nfl_id:'11',is_ball:false,x:40.2,y:12.1,speed_yards_per_s:2.8,acceleration_yards_per_s2:.8},
      ],ball:null},
    ],
  };
}
test('trusted shape preserves observed numeric tracking',()=>{
  const result=parseHistoricalReplay(valid());
  assert.equal(result.frames.length,2);
  assert.equal(result.frames[1].players[0].acceleration_yards_per_s2,.8);
});
test('reject fabricated authority and omitted provenance',()=>{
  const a=valid();a.data_mode='LIVE_LICENSED';
  assert.throws(()=>parseHistoricalReplay(a),/research-labeled/);
  const b=valid();b.source='';
  assert.throws(()=>parseHistoricalReplay(b),/source attribution/);
});
test('reject nonfinite and nonnumeric speed and acceleration before rendering',()=>{
  for(const value of [NaN,Infinity,'fast']){
    const x=valid();
    x.frames[0].players[0].speed_yards_per_s=value;
    assert.throws(()=>parseHistoricalReplay(x),/Invalid numeric tracking observation/);
  }
  const bad=valid();
  bad.frames[1].players[0].acceleration_yards_per_s='rapid';
  assert.throws(()=>parseHistoricalReplay(bad),/Invalid numeric tracking observation/);
});
test('reject duplicate player identities and missing entities',()=>{
  const x=valid();x.frames[0].players.push({...x.frames[0].players[0]});
  assert.throws(()=>parseHistoricalReplay(x),/Duplicate tracked identity/);
  const y=valid();y.frames[0].players=[null];
  assert.throws(()=>parseHistoricalReplay(y),/Invalid tracked entity/);
});
test('reject bad frame timing, boundaries and coverage metadata',()=>{
  const a=valid();a.frames[1].frame_id=1;
  assert.throws(()=>parseHistoricalReplay(a),/increasing/);
  const b=valid();b.frames[1].players[0].x=121;
  assert.throws(()=>parseHistoricalReplay(b),/field-space coordinates/);
  const c=valid();c.frame_coverage=1.25;
  assert.throws(()=>parseHistoricalReplay(c),/coverage/);
});
