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
    missing_frame_count:0,
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
  bad.frames[1].players[0].acceleration_yards_per_s2='rapid';
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

test('coverage must match missing frames and exact recorded frame IDs',()=>{
  const x=valid();x.frames[1].frame_id=3;x.frames[1].t_seconds_nominal=.2;
  assert.throws(()=>parseHistoricalReplay(x),/coverage metadata disagrees/);
  x.missing_frame_count=1;x.frame_coverage=2/3;
  assert.equal(parseHistoricalReplay(x).missing_frame_count,1);
});
test('ball and player identities cannot be swapped by an import payload',()=>{
  const x=valid();
  x.frames[0].ball={nfl_id:'42',is_ball:true,x:40,y:10};
  assert.throws(()=>parseHistoricalReplay(x),/Ball identity/);
});


test('audited off-field source exclusions remain visible and validated',()=>{
  const x=valid();
  x.position_quality={
    policy:'omit_off_field_with_audit',
    omitted_missing_position_rows:1,
    omitted_off_field_position_rows:2,
    omitted_total_position_rows:3,
    affected_source_frame_ids:[2],
    never_clamped_or_interpolated:true,
  };
  assert.equal(parseHistoricalReplay(x).position_quality.omitted_total_position_rows,3);
  const invalid=structuredClone(x);
  invalid.position_quality.omitted_total_position_rows=0;
  assert.throws(()=>parseHistoricalReplay(invalid),/observation exclusion audit/);
  const id=structuredClone(x);
  id.position_quality.affected_source_frame_ids=[999];
  assert.throws(()=>parseHistoricalReplay(id),/observation exclusion audit/);
  const clamp=structuredClone(x);
  clamp.position_quality.never_clamped_or_interpolated=false;
  assert.throws(()=>parseHistoricalReplay(clamp),/observation exclusion audit/);
});


test('source-charted down, personnel and possession metadata must reconcile',()=>{
  const r=valid();
  r.possession_team='KC';
  r.source_play_metadata={
    provenance:'PINNED_OFFICIAL_PLAYS_AND_GAMES_CSV',
    season:2017,week:1,home_team:'NE',visitor_team:'KC',
    possession_team:'KC',offense_side:'away',
    quarter:1,down:3,yards_to_go:7,
    offense_formation_charted:'SHOTGUN',
    offense_personnel_charted:'1 RB, 2 TE, 2 WR',
  };
  assert.equal(parseHistoricalReplay(r).source_play_metadata.offense_formation_charted,'SHOTGUN');
  const team=structuredClone(r);team.source_play_metadata.offense_side='home';
  assert.throws(()=>parseHistoricalReplay(team),/metadata is internally inconsistent/);
  const possession=structuredClone(r);possession.possession_team='NE';
  assert.throws(()=>parseHistoricalReplay(possession),/metadata is internally inconsistent/);
  const chart=structuredClone(r);chart.source_play_metadata.offense_formation_charted='A'.repeat(91);
  assert.throws(()=>parseHistoricalReplay(chart),/metadata is internally inconsistent/);
  const special=structuredClone(r);
  special.source_play_metadata.down=null;
  special.source_play_metadata.yards_to_go=null;
  special.source_play_metadata.offense_formation_charted=null;
  assert.equal(parseHistoricalReplay(special).source_play_metadata.down,null);
});
