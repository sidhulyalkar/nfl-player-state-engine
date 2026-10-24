import test from 'node:test';
import assert from 'node:assert/strict';
import {recordedNote,observedNearestOpponent,opponentProximitySeries,replayChapters} from './recordedCommentary.ts';

const player=(id,side,x,y)=>({nfl_id:id,is_ball:false,side,team:side==='offense'?'KC':'NE',name:id,jersey:'10',x,y,z:null,speed_yards_per_s:0});
const frame=(frame_id,t,events=[],wrX=40,defX=44)=>({frame_id,t_seconds_nominal:t,events,ball:null,players:[
  player('WR','offense',wrX,20),player('CB','defense',defX,20),
]});
const replay=(frames)=>({data_mode:'HISTORICAL_RESEARCH',tracking_fidelity:'RECORDED_FRAMES',
  game_id:'2017090700',play_id:'938',frames,
  frame_count:frames.length,missing_frame_count:0,frame_coverage:1,
  source:'test only',source_file_sha256:'a'.repeat(64),source_license_identifier:'test-fixture',
  play_direction:'right',
});
test('source tagged chapters label exact events, never assert matchup or coverage',()=>{
  const r=replay([frame(1,0,['ball_snap']),frame(2,.1,['pass_forward']),frame(3,.2)]);
  const chapters=replayChapters(r);
  assert.deepEqual(chapters.map(x=>x.title),['Snap recorded','Forward pass released']);
  const note=recordedNote(r,2,false,'WR');
  assert.equal(note.provenance,'SOURCE_EVENT');
  assert.equal(note.sourceFrameId,2);
  assert.match(note.detail,/Source tag/);
  assert.doesNotMatch(note.detail,/targeted mismatch|good block|Cover-2/);
});
test('source absent uses measured nearest opposite-side distance only',()=>{
  const r=replay([frame(1,0)]);
  const note=recordedNote(r,0,false,'WR');
  assert.equal(note.provenance,'OBSERVED_GEOMETRY');
  assert.match(note.detail,/4.0 yards/);
  assert.equal(observedNearestOpponent(r.frames[0],'WR').playerId,'CB');
});
test('missing side, unknown player and absent opponent do not fabricate metrics',()=>{
  const f=frame(1,0);
  f.players[1].side=null;
  assert.equal(observedNearestOpponent(f,'WR'),null);
  assert.equal(observedNearestOpponent(f,'UNKNOWN'),null);
  const r=replay([f]);
  assert.match(recordedNote(r,0,false,'WR').detail,/Only positions/);
});
test('explicit sample gaps break line segments, with no interpolation or bridging',()=>{
  const r=replay([frame(1,0),frame(2,.1),frame(4,.3),frame(5,.4)]);
  const data=opponentProximitySeries(r,'WR',3);
  assert.equal(data.paths.length,2);
  assert.deepEqual(data.paths.map(x=>x.map(y=>y.frameId)),[[1,2],[4,5]]);
  assert.equal(data.observed,4);
});
test('absent tracked player creates a gap and latest dot is absent',()=>{
  const frames=[frame(1,0),frame(2,.1),frame(3,.2)];
  frames[1].players=frames[1].players.filter(p=>p.nfl_id!=='WR');
  frames[2].players=frames[2].players.filter(p=>p.nfl_id!=='WR');
  const r=replay(frames), chart=opponentProximitySeries(r,'WR',2);
  assert.equal(chart.paths.length,1);
  assert.equal(chart.observed,1);
  assert.equal(chart.latest,null);
});
test('playback gap refuses any new source claim or proximity interpretation',()=>{
  const r=replay([frame(1,0,['ball_snap']),frame(3,.2)]);
  const note=recordedNote(r,1,true,'WR');
  assert.equal(note.provenance,'EVIDENCE_GAP');
  assert.equal(note.rawEvent,null);
});
