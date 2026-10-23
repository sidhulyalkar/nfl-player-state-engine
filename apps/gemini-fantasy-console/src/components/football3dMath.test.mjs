import test from 'node:test';
import assert from 'node:assert/strict';
import {
  fieldPoint, defaultOrbit, orbitCamera, projectToScreen, lensUniforms,
  trackingFocus, trackingDistance, sourceSnapIndex, observedTrailSegments, norm, cross, dot, clamp,
} from './football3dMath.ts';

test('real NFL yards map to centered world coordinates without rescaling', () => {
  assert.deepEqual(fieldPoint(0,0),[-60,0,-26.65]);
  assert.deepEqual(fieldPoint(60,26.65),[0,0,0]);
  assert.deepEqual(fieldPoint(120,53.3),[60,0,26.65]);
  const point=fieldPoint(50,20,1.6);
  assert.equal(point[0],-10);
  assert.equal(point[1],1.6);
  assert.ok(Math.abs(point[2]+6.65)<1e-9);
});
test('invalid tracking points fail closed rather than appearing on field', () => {
  for (const args of [[-1,12],[120.01,12],[20,53.31],[NaN,1],[1,Infinity]]) {
    assert.throws(()=>fieldPoint(...args),/Invalid/);
  }
});
test('camera basis is orthonormal for every angle, including overhead', () => {
  for(const mode of ['broadcast','all22','overhead']){
    const basis=orbitCamera(defaultOrbit(mode),1040/590);
    assert.ok(Math.abs(dot(basis.forward,basis.right))<1e-12);
    assert.ok(Math.abs(dot(basis.forward,basis.up))<1e-12);
    assert.ok(Math.abs(dot(basis.up,basis.right))<1e-12);
    assert.ok(Math.abs(Math.hypot(...basis.forward)-1)<1e-12);
    assert.ok(Math.abs(Math.hypot(...basis.up)-1)<1e-12);
    assert.equal(lensUniforms(basis).length,4);
    const center=projectToScreen([0,0,0],basis,1040,590);
    assert.equal(center.visible,true);
    assert.ok(Math.abs(center.x-520)<1e-8);
    assert.ok(Math.abs(center.y-295)<1e-8);
    assert.ok(center.depth>0);
  }
});
test('camera rejects degenerate aspect ratios and behind-camera points', () => {
  assert.throws(()=>orbitCamera(defaultOrbit('broadcast'),0),/aspect/);
  const camera=orbitCamera(defaultOrbit('all22'),1.7);
  const behind=projectToScreen(camera.eye.map((n,i)=>n-camera.forward[i]*5),camera,1000,600);
  assert.equal(behind.visible,false);
});
test('focus uses observed positions and caps camera target; never invents scrimmage', () => {
  assert.deepEqual(trackingFocus([]),[0,0,0]);
  const center=trackingFocus([{x:50,y:23},{x:70,y:30.3}]);
  assert.ok(center.every((v)=>Math.abs(v)<1e-9));
  assert.deepEqual(trackingFocus([{x:120,y:53.3}]),[40,0,15]);
});
test('Euclidean separation is grounded in yards, not a coverage inference', () => {
  assert.equal(trackingDistance({x:10,y:10},{x:13,y:14}),5);
  assert.equal(trackingDistance({x:30,y:30},{x:30,y:30}),0);
  assert.equal(clamp(360,40,260),260);
  assert.deepEqual(norm(cross([1,0,0],[0,1,0])),[0,0,1]);
});

test('only source-tagged snap frames become alignment anchors',()=>{
  assert.equal(sourceSnapIndex([{events:['pass_forward']},{events:[]},{events:['BALL_SNAP']}]),2);
  assert.equal(sourceSnapIndex([{events:['pass_forward']},{events:[]}]),-1);
});
test('recorded trails do not bridge missing frames or absent player identity',()=>{
  const frames=[
    {frame_id:1,players:[{nfl_id:'WR',x:40,y:10,side:'offense'},{nfl_id:'CB',x:44,y:10,side:'defense'}]},
    {frame_id:2,players:[{nfl_id:'WR',x:40.2,y:11,side:'offense'},{nfl_id:'CB',x:43.8,y:11,side:'defense'}]},
    {frame_id:4,players:[{nfl_id:'WR',x:45,y:13,side:'offense'}]},
    {frame_id:5,players:[{nfl_id:'WR',x:46,y:14,side:'offense'},{nfl_id:'OTHER',x:47,y:13,side:'defense'}]},
  ];
  const result=observedTrailSegments(frames,3);
  assert.equal(result.length,3);
  assert.deepEqual(result.map(p=>p.id),['WR','CB','WR']);
  assert.deepEqual(result[2].from,[45,13]);
  assert.deepEqual(result[2].to,[46,14]);
  assert.ok(!result.some(p=>p.from[0]===40.2&&p.to[0]===45));
});
