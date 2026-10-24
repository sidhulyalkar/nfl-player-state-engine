import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { parseReplaySessionManifest, verifyReplaySessionFiles } from './historicalReplayManifest.ts';

const HASH='a'.repeat(64);
const GAME='2017090700';
const LICENSE='local fixture terms reviewed';
function replay(play_id='938'){
  return {
    data_mode:'HISTORICAL_RESEARCH',tracking_fidelity:'RECORDED_FRAMES',
    game_id:GAME,play_id,source:'fixture data only',source_file_sha256:HASH,
    source_license_identifier:LICENSE,play_direction:null,rows:6,
    frame_count:2,missing_frame_count:0,frame_coverage:1,
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
      {frame_id:1,t_seconds_nominal:0,players:[{nfl_id:'11',is_ball:false,x:40,y:21,
        speed_yards_per_s:2,team:'away',side:'offense'}],ball:null,events:['ball_snap']},
      {frame_id:2,t_seconds_nominal:.1,players:[{nfl_id:'11',is_ball:false,x:41,y:21,
        speed_yards_per_s:3,team:'away',side:'offense'}],ball:null,events:[]},
    ],
  };
}
const encode=(x)=>new TextEncoder().encode(JSON.stringify(x));
function fixture(){
  const source=(file)=>({file,bytes:100,sha256:HASH,git_blob_sha1:'b'.repeat(40),identity_match:true});
  const r=replay(),bytes=encode(r),sha=createHash('sha256').update(bytes).digest('hex');
  const filename=GAME+'-938-research-replay.json';
  const manifest={
    schema_version:1,data_mode:'HISTORICAL_RESEARCH_BATCH_MANIFEST',
    qualification_status:'NONCANONICAL_FIXTURE_ONLY',game_id:GAME,
    source_file_sha256:HASH,source_identities:{
      tracking:source('tracking_gameId_2017090700.csv'),
      games:source('games.csv'),plays:source('plays.csv'),
    },
    source_video_alignment_verified:false,model_training_authorized:false,
    commercial_reuse_authorized:false,license_declaration:LICENSE,
    play_count:1,plays:[{
      play_id:'938',file:filename,sha256:sha,source_rows:6,
      recorded_frames:2,missing_source_frames:0,omitted_position_rows:0,
      possession_team:'KC',metadata_provenance:'NONCANONICAL_TEST_FIXTURE',
    }],
  };
  return {manifest,bytes,filename};
}
const asFile=(name,bytes)=>({
  name,arrayBuffer:async()=>bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength),
});

test('fixture manifest plus SHA-256-matching file imports as one session',async()=>{
  const {manifest,bytes,filename}=fixture();
  const parsed=parseReplaySessionManifest(manifest);
  const imports=await verifyReplaySessionFiles(parsed,[asFile(filename,bytes)]);
  assert.equal(imports.length,1);
  assert.equal(imports[0].source_play_metadata.provenance,'NONCANONICAL_TEST_FIXTURE');
});
test('raw-byte edits are rejected even when JSON is parseable',async()=>{
  const {manifest,bytes,filename}=fixture();
  const edited=new Uint8Array(bytes.length+1);
  edited.set(bytes);edited[bytes.length]=32;
  await assert.rejects(
    verifyReplaySessionFiles(parseReplaySessionManifest(manifest),[asFile(filename,edited)]),
    /SHA-256 mismatch/,
  );
});
test('coherently rehashed but semantically conflicting replay fails closed',async()=>{
  const {manifest,filename}=fixture();
  const corrupted=replay();corrupted.source_license_identifier='different fixture declaration';
  const bytes=encode(corrupted);
  manifest.plays[0].sha256=createHash('sha256').update(bytes).digest('hex');
  await assert.rejects(
    verifyReplaySessionFiles(parseReplaySessionManifest(manifest),[asFile(filename,bytes)]),
    /Replay conflicts/,
  );
});
test('missing, extra and duplicate files are all rejected',async()=>{
  const {manifest,bytes,filename}=fixture();
  const parsed=parseReplaySessionManifest(manifest);
  for(const files of [[],[asFile(filename,bytes),asFile(filename,bytes)],[asFile('evil.json',bytes)]]){
    await assert.rejects(verifyReplaySessionFiles(parsed,files),/Select every|Unexpected/);
  }
});
test('reject forged permissions or video authority and inconsistent source declaration',()=>{
  const {manifest}=fixture();
  for(const [key,value] of [
    ['source_video_alignment_verified',true],
    ['model_training_authorized',true],
    ['commercial_reuse_authorized',true],
    ['qualification_status','FILM_VERIFIED'],
  ]){
    const invalid=structuredClone(manifest);
    invalid[key]=value;
    assert.throws(()=>parseReplaySessionManifest(invalid),/Invalid research session manifest/);
  }
  const bad=structuredClone(manifest);
  bad.source_identities.tracking.sha256='c'.repeat(64);
  assert.throws(()=>parseReplaySessionManifest(bad),/tracking SHA-256/);
});
test('invalid path, row count and provenance cannot enter an atomic session',()=>{
  const {manifest}=fixture();
  const badPath=structuredClone(manifest);
  badPath.plays[0].file='../938.json';
  assert.throws(()=>parseReplaySessionManifest(badPath),/play entry/);
  const wrongRows=structuredClone(manifest);
  wrongRows.plays[0].source_rows=-1;
  assert.throws(()=>parseReplaySessionManifest(wrongRows),/play entry/);
  const wrongProvenance=structuredClone(manifest);
  wrongProvenance.plays[0].metadata_provenance='PINNED_OFFICIAL_PLAYS_AND_GAMES_CSV';
  assert.throws(()=>parseReplaySessionManifest(wrongProvenance),/play entry/);
});
