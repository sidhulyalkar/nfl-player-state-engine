import test from 'node:test';
import assert from 'node:assert/strict';
import {parsePlayCatalog,catalogMatchesReplay} from './historicalPlayCatalog.ts';
function valid(){
  return {schema_version:1,data_mode:'HISTORICAL_RESEARCH_METADATA_ONLY',
    game_id:'2017090700',source:'CI-generated summary only',source_sha256:'b'.repeat(64),
    source_bytes:1024,source_rows:4,play_count:1,positions_included:false,
    source_video_alignment_verified:false,plays:[{
      game_id:'2017090700',play_id:'938',source_rows:4,recorded_frames:2,
      first_frame_id:1,last_frame_id:3,missing_frame_ids:1,
      coverage_ratio:2/3,duration_seconds_nominal:.2,unique_players:1,
      max_players_per_frame:1,ball_recorded_frames:2,source_events:{ball_snap:[1],touchdown:[3]},
      unrenderable_position_rows:0,off_field_rows:0,missing_xy_rows:0,
      affected_source_frame_ids:[],
    }]};
}
test('source event catalog parses without player tracking',()=>{
  const c=parsePlayCatalog(valid());
  assert.equal(c.plays.length,1);
  assert.deepEqual(c.plays[0].source_events.touchdown,[3]);
  assert.equal(catalogMatchesReplay(c.plays[0],{game_id:'2017090700',play_id:'938',frame_count:2,missing_frame_count:1,rows:4}),true);
  assert.equal(catalogMatchesReplay(c.plays[0],{game_id:'2017090700',play_id:'938',frame_count:2,missing_frame_count:0}),false);
});
test('catalog rejects included positions and unsupported claims',()=>{
  const a=valid();a.positions_included=true;
  assert.throws(()=>parsePlayCatalog(a),/position-free/);
  const b=valid();b.source_video_alignment_verified=true;
  assert.throws(()=>parsePlayCatalog(b),/position-free/);
  const c=valid();c.plays[0].players=[{x:40,y:21}];
  assert.throws(()=>parsePlayCatalog(c),/must not contain/);
});
test('catalog fails closed on coverage, duplicate events and omitted rows',()=>{
  const a=valid();a.plays[0].missing_frame_ids=0;
  assert.throws(()=>parsePlayCatalog(a),/inconsistent/);
  const b=valid();b.plays[0].source_events.touchdown=[3,3];
  assert.throws(()=>parsePlayCatalog(b),/event evidence/);
  const c=valid();c.plays[0].off_field_rows=1;
  assert.throws(()=>parsePlayCatalog(c),/inconsistent/);
  const d=valid();d.source_rows=5;
  assert.throws(()=>parsePlayCatalog(d),/totals disagree/);
});
test('catalog rejects rows from another game and duplicate play IDs',()=>{
  const a=valid();a.plays[0].game_id='2017091000';
  assert.throws(()=>parsePlayCatalog(a),/identity/);
  const b=valid();b.plays.push({...b.plays[0]});b.play_count=2;b.source_rows=8;
  assert.throws(()=>parsePlayCatalog(b),/identity/);
});
