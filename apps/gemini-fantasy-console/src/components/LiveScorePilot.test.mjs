import test from 'node:test';
import assert from 'node:assert/strict';
import {liveScoreDeltas} from './LiveScorePilot.tsx';

const game=(away=7,home=10,state='in')=>({
  game_id:'2026_07_GB_DET',provider_event_id:'401899999',
  home_team:'DET',away_team:'GB',home_score:home,away_score:away,
  kickoff_utc:'2026-10-25T20:25:00Z',state,
  period:2,clock:'12:53',status_text:'2nd 12:53',
  possession:null,down:null,distance:null,tracking_available:false,play_by_play_available:false,
});
const board=(time,score=game(),stale=false,week=7)=>({
  schema_version:1,authority:'EXPERIMENTAL_UNLICENSED_SCOREBOARD_EVALUATION',
  data_mode:'EXPERIMENTAL_LIVE_SCORE_STATUS_ONLY',season:2026,week,
  served_at_utc:time,games:[score],
  source:{name:'test',url:'https://example.invalid',fetched_at_utc:time,
    age_seconds:0,stale,throttled:false,refresh_error:null,rights_status:'NOT_REVIEWED_FOR_REDISTRIBUTION',
    official_api_contract:false,live_play_by_play:false,live_tracking:false},
});
const a='2026-10-25T21:00:00Z',b='2026-10-25T21:00:30Z';
test('initial fetch is baseline, not invented touchdown',()=>{
  assert.deepEqual(liveScoreDeltas(null,board(a)),[]);
});
test('score changes are generic observed revisions, including corrections downward',()=>{
  const result=liveScoreDeltas(board(a,game(7,10)),board(b,game(7,7)));
  assert.equal(result.length,1);
  assert.equal(result[0].kind,'score');
  assert.match(result[0].detail,/scoring play, timing and player attribution are unknown/);
});
test('in-progress to final transition is a source status update, not an inferred play',()=>{
  const result=liveScoreDeltas(board(a),board(b,game(7,10,'post')));
  assert.equal(result.length,1);
  assert.equal(result[0].kind,'state');
});
test('stale, same-timestamp and other-week feed cannot create false alerts',()=>{
  assert.deepEqual(liveScoreDeltas(board(a),board(b,game(14,10),true)),[]);
  assert.deepEqual(liveScoreDeltas(board(a),board(a,game(14,10))),[]);
  assert.deepEqual(liveScoreDeltas(board(a),board(b,game(14,10),false,8)),[]);
});
test('provider event identity drift is not joined by team abbreviations',()=>{
  const next=game(14,10);next.provider_event_id='other-provider-id';
  assert.deepEqual(liveScoreDeltas(board(a),board(b,next)),[]);
});
test('timestamp parse failures produce no published update',()=>{
  assert.deepEqual(liveScoreDeltas(board('invalid'),board(b,game(14,10))),[]);
  assert.deepEqual(liveScoreDeltas(board(a),board('invalid',game(14,10))),[]);
});
