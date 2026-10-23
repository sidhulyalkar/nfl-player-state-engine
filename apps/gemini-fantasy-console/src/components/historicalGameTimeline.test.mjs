import test from 'node:test';
import assert from 'node:assert/strict';
import {parseGameTimeline,timelineReplayMatch} from './historicalGameTimeline.ts';

const HEX='a'.repeat(64);
function makeCatalog(){
  return {schema_version:1,data_mode:'HISTORICAL_RESEARCH_METADATA_ONLY',
    positions_included:false,source_video_alignment_verified:false,
    game_id:'2017090700',source_sha256:HEX,source_bytes:1000,source_rows:10,play_count:2,plays:[
      {game_id:'2017090700',play_id:'4',source_rows:4,recorded_frames:2,missing_frame_ids:0},
      {game_id:'2017090700',play_id:'12',source_rows:6,recorded_frames:3,missing_frame_ids:0},
    ]};
}
function makeTimeline(){
  return {schema_version:1,data_mode:'HISTORICAL_RESEARCH_GAME_TIMELINE',
    qualification_status:'SYNTHETIC_OR_NONCANONICAL_FIXTURE_ONLY',
    positions_included:false,drive_boundaries_verified:false,
    source_video_alignment_verified:false,commercial_reuse_authorized:false,
    model_training_authorized:false,
    game_id:'2017090700',season:2017,week:1,home_team:'NE',away_team:'KC',
    tracking_source_sha256:HEX,plays_source_sha256:'b'.repeat(64),
    games_source_sha256:'c'.repeat(64),source_commit:null,play_count:2,plays:[
      {game_id:'2017090700',play_id:'4',quarter:1,down:1,yards_to_go:8,
        possession_team:'NE',offense_side:'home',game_clock_charted:'09:28',yardline_side_charted:'NE',yardline_number_charted:25,
        description_charted:'Verified source description',formation_charted:'SHOTGUN',
        personnel_charted:null,source_tracking_rows:4},
      {game_id:'2017090700',play_id:'12',quarter:2,down:3,yards_to_go:8,
        possession_team:'KC',offense_side:'away',game_clock_charted:null,yardline_side_charted:null,yardline_number_charted:null,
        description_charted:null,formation_charted:null,
        personnel_charted:'1 RB, 3 WR, 1 TE',source_tracking_rows:6},
    ]};
}
test('strict source-matched timeline imports and retains charted metadata',()=>{
  const t=parseGameTimeline(makeTimeline(),makeCatalog());
  assert.equal(t.plays.length,2);
  assert.equal(t.plays[0].quarter,1);
  assert.equal(t.drive_boundaries_verified,false);
  assert.equal(t.positions_included,false);
});
test('source SHA and partial play coverage fail closed',()=>{
  const a=makeTimeline();a.tracking_source_sha256='d'.repeat(64);
  assert.throws(()=>parseGameTimeline(a,makeCatalog()),/identifiers/);
  const b=makeTimeline();b.plays.pop();b.play_count=1;
  assert.throws(()=>parseGameTimeline(b,makeCatalog()),/coverage/);
});
test('spoofed live/tracking permissions and invented drive truth are refused',()=>{
  const a=makeTimeline();a.drive_boundaries_verified=true;
  assert.throws(()=>parseGameTimeline(a,makeCatalog()),/position-free/);
  const b=makeTimeline();b.plays[0].players=[{x:40,y:20}];
  assert.throws(()=>parseGameTimeline(b,makeCatalog()),/tracking frames/);
  const c=makeTimeline();c.commercial_reuse_authorized=true;
  assert.throws(()=>parseGameTimeline(c,makeCatalog()),/position-free/);
});
test('changed source row counts, clock and possession fail closed',()=>{
  const a=makeTimeline();a.plays[0].source_tracking_rows=99;
  assert.throws(()=>parseGameTimeline(a,makeCatalog()),/identities/);
  const b=makeTimeline();b.plays[0].game_clock_charted='99:99';
  assert.throws(()=>parseGameTimeline(b,makeCatalog()),/metadata/);
  const c=makeTimeline();c.plays[0].possession_team='DAL';
  assert.throws(()=>parseGameTimeline(c,makeCatalog()),/metadata/);
});
test('three-dimensional replay selection requires matching recorded identity and source',()=>{
  const catalog=makeCatalog(), t=parseGameTimeline(makeTimeline(),catalog);
  const replay={game_id:'2017090700',play_id:'4',frame_count:2,
    missing_frame_count:0,source_file_sha256:HEX};
  assert.equal(timelineReplayMatch(t.plays[0],catalog,replay),true);
  assert.equal(timelineReplayMatch(t.plays[0],catalog,{...replay,source_file_sha256:'e'.repeat(64)}),false);
  assert.equal(timelineReplayMatch(t.plays[0],catalog,{...replay,frame_count:1}),false);
});
