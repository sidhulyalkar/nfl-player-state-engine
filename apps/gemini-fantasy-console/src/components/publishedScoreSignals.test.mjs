import test from 'node:test';
import assert from 'node:assert/strict';
import {publishedScoreSignals} from './publishedScoreSignals.ts';

const board=(fetched,away,home,week=7,stale=false)=>({
  season:2026,week,
  source:{fetched_at_utc:fetched,integrity_verified:true,stale},
  games:[{game_id:'2026_101',away_team:'KC',home_team:'NE',
    away_score:away,home_score:home}],
});
const first='2026-10-20T15:00:00Z',second='2026-10-20T15:05:00Z';
test('initial snapshot is baseline, never masquerades as a live scoring event',()=>{
  assert.deepEqual(publishedScoreSignals(null,board(first,3,0)),[]);
});
test('published score corrections, including decreases, are described as revisions',()=>{
  const result=publishedScoreSignals(board(first,14,7),board(second,10,7));
  assert.equal(result.length,1);
  assert.equal(result[0].kind,'PUBLISHED_SCORE_REVISION');
  assert.match(result[0].text,/Published score/);
  assert.match(result[0].text,/not a confirmed scoring play/);
});
test('scores first appearing are not treated as a touchdown',()=>{
  const result=publishedScoreSignals(board(first,null,null),board(second,0,0));
  assert.equal(result[0].kind,'FIRST_PUBLISHED_SCORE');
  assert.doesNotMatch(result[0].text,/touchdown|field goal|extra point/i);
});
test('same timestamp, old source revision, other week and stale data create no events',()=>{
  assert.deepEqual(publishedScoreSignals(board(first,0,0),board(first,7,0)),[]);
  assert.deepEqual(publishedScoreSignals(board(second,0,0),board(first,7,0)),[]);
  assert.deepEqual(publishedScoreSignals(board(first,0,0,6),board(second,7,0,7)),[]);
  assert.deepEqual(publishedScoreSignals(board(first,0,0),board(second,7,0,7,true)),[]);
});
test('identity mismatch and partial scores are rejected',()=>{
  let next=board(second,7,0);
  next.games[0].away_team='XX';
  assert.deepEqual(publishedScoreSignals(board(first,0,0),next),[]);
  assert.deepEqual(publishedScoreSignals(board(first,0,0),board(second,7,null)),[]);
});
test('source identity failure never emits commentary',()=>{
  const newBoard=board(second,7,0);
  newBoard.source.integrity_verified=false;
  assert.deepEqual(publishedScoreSignals(board(first,0,0),newBoard),[]);
});
