/** Cross-surface contract: pinned-source metadata, manifest-checked replay,
 * browser library and observed geometry must agree on the same identity.
 * This is a SYNTHETIC fixture, never proof of official NFL source qualification.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {parsePlayCatalog} from './historicalPlayCatalog.ts';
import {parseGameTimeline,timelineReplayMatch} from './historicalGameTimeline.ts';
import {parseReplaySessionManifest,verifyReplaySessionFiles} from './historicalReplayManifest.ts';
import {mergeReplayLibrary} from './historicalReplayLibrary.ts';
import {nearestOpponentSamples} from './observedSeparation.ts';

const SHA='a'.repeat(64), GAME='2017090700', PLAY='938', TERMS='synthetic fixture only';
const PLAY_FILE=GAME+'-'+PLAY+'-research-replay.json';
function fixture(){
  const catalog=parsePlayCatalog({
    schema_version:1,data_mode:'HISTORICAL_RESEARCH_METADATA_ONLY',
    positions_included:false,source_video_alignment_verified:false,
    game_id:GAME,source:'synthetic local fixture',source_sha256:SHA,
    source_bytes:1024,source_rows:6,play_count:1,plays:[{
      game_id:GAME,play_id:PLAY,source_rows:6,recorded_frames:2,
      first_frame_id:1,last_frame_id:2,missing_frame_ids:0,
      coverage_ratio:1,duration_seconds_nominal:.1,unique_players:2,
      max_players_per_frame:2,ball_recorded_frames:0,source_events:{ball_snap:[1]},
      unrenderable_position_rows:0,off_field_rows:0,missing_xy_rows:0,
      affected_source_frame_ids:[],
    }],
  });
  const timeline=parseGameTimeline({
    schema_version:1,data_mode:'HISTORICAL_RESEARCH_GAME_TIMELINE',
    qualification_status:'SYNTHETIC_OR_NONCANONICAL_FIXTURE_ONLY',
    positions_included:false,drive_boundaries_verified:false,
    source_video_alignment_verified:false,commercial_reuse_authorized:false,
    model_training_authorized:false,game_id:GAME,season:2017,week:1,
    home_team:'NE',away_team:'KC',tracking_source_sha256:SHA,
    plays_source_sha256:'b'.repeat(64),games_source_sha256:'c'.repeat(64),
    source_commit:null,play_count:1,plays:[{
      game_id:GAME,play_id:PLAY,quarter:1,down:3,yards_to_go:7,
      possession_team:'KC',offense_side:'away',game_clock_charted:'09:28',
      yardline_side_charted:'NE',yardline_number_charted:25,
      description_charted:'Synthetic play description',formation_charted:'SHOTGUN',
      personnel_charted:null,source_tracking_rows:6,
    }],
  },catalog);
  const tracked=(id,side,x)=>({nfl_id:id,is_ball:false,team:side==='offense'?'away':'home',
    side,name:id,jersey:'11',x,y:20,z:null,speed_yards_per_s:1});
  const replay={
    data_mode:'HISTORICAL_RESEARCH',tracking_fidelity:'RECORDED_FRAMES',
    game_id:GAME,play_id:PLAY,source:'synthetic fixture',
    source_file_sha256:SHA,source_license_identifier:TERMS,
    play_direction:null,rows:6,frame_count:2,missing_frame_count:0,frame_coverage:1,
    possession_team:'KC',
    source_play_metadata:{
      provenance:'NONCANONICAL_TEST_FIXTURE',season:2017,week:1,
      home_team:'NE',visitor_team:'KC',possession_team:'KC',offense_side:'away',
      quarter:1,down:3,yards_to_go:7,
      offense_formation_charted:'SHOTGUN',offense_personnel_charted:null,
    },
    position_quality:{
      policy:'omit_off_field_with_audit',omitted_missing_position_rows:0,
      omitted_off_field_position_rows:0,omitted_total_position_rows:0,
      affected_source_frame_ids:[],never_clamped_or_interpolated:true,
    },
    frames:[
      {frame_id:1,t_seconds_nominal:0,players:[tracked('WR','offense',40),tracked('CB','defense',44)],ball:null,events:['ball_snap']},
      {frame_id:2,t_seconds_nominal:.1,players:[tracked('WR','offense',41),tracked('CB','defense',43)],ball:null,events:[]},
    ],
  };
  const encoded=new TextEncoder().encode(JSON.stringify(replay));
  const hex=createHash('sha256').update(encoded).digest('hex');
  const source=file=>({file,bytes:1024,sha256:SHA,git_blob_sha1:'b'.repeat(40),identity_match:true});
  const manifest=parseReplaySessionManifest({
    schema_version:1,data_mode:'HISTORICAL_RESEARCH_BATCH_MANIFEST',
    qualification_status:'NONCANONICAL_FIXTURE_ONLY',
    game_id:GAME,source_file_sha256:SHA,
    source_identities:{tracking:source('tracking_gameId_2017090700.csv'),plays:source('plays.csv'),games:source('games.csv')},
    source_video_alignment_verified:false,model_training_authorized:false,
    commercial_reuse_authorized:false,license_declaration:TERMS,play_count:1,
    plays:[{play_id:PLAY,file:PLAY_FILE,sha256:hex,source_rows:6,
      recorded_frames:2,missing_source_frames:0,omitted_position_rows:0,
      possession_team:'KC',metadata_provenance:'NONCANONICAL_TEST_FIXTURE'}],
  });
  const file={name:PLAY_FILE,arrayBuffer:async()=>encoded.buffer.slice(encoded.byteOffset,encoded.byteOffset+encoded.byteLength)};
  return {catalog,timeline,manifest,file};
}
test('complete synthetic research workflow retains matching source identity and geometry',async()=>{
  const {catalog,timeline,manifest,file}=fixture();
  const imports=await verifyReplaySessionFiles(manifest,[file]);
  const library=mergeReplayLibrary([],imports);
  assert.equal(library.length,1);
  assert.equal(timelineReplayMatch(timeline.plays[0],catalog,library[0]),true);
  const s=nearestOpponentSamples(library[0].frames,'WR');
  assert.deepEqual(s.map(x=>x.distance_yards),[4,2]);
  assert.deepEqual(s.map(x=>x.opponent_id),['CB','CB']);
  assert.equal(timeline.model_training_authorized,false);
  assert.equal(manifest.source_video_alignment_verified,false);
});
test('full workflow rejects a mutated replay and keeps existing immutable library',async()=>{
  const {manifest,file}=fixture();
  const existing=mergeReplayLibrary([],await verifyReplaySessionFiles(manifest,[file]));
  const original=file.arrayBuffer;
  const corrupt={name:PLAY_FILE,arrayBuffer:async()=>{
    const raw=new Uint8Array(await original());
    const copy=new Uint8Array(raw.length+1);
    copy.set(raw);copy[raw.length]=32;
    return copy.buffer;
  }};
  await assert.rejects(verifyReplaySessionFiles(manifest,[corrupt]),/SHA-256 mismatch/);
  assert.equal(existing.length,1);
  assert.equal(existing[0].source_file_sha256,SHA);
});
