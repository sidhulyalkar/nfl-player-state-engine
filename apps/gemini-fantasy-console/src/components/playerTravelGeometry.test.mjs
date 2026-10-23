import test from 'node:test';
import assert from 'node:assert/strict';
import { measuredTravelBasis, travelPoint, travelChevron } from './playerTravelGeometry.ts';

test('eastbound recorded x displacement maps to increasing NFL x',()=>{
  const b=measuredTravelBasis({dx:.35,dy:0,speed:3.5});
  assert.ok(b);
  assert.equal(b.forwardX,1); assert.equal(b.forwardY,0);
  assert.deepEqual(travelPoint({x:55,y:25},b,0,2),{x:57,y:25});
  assert.deepEqual(travelChevron({x:55,y:25},{dx:.35,dy:0,speed:3.5}),[
    {x:56.95,y:25},{x:56.25,y:24.45},{x:56.25,y:25.55},
  ]);
});
test('north and diagonal vectors have an orthogonal geometric basis',()=>{
  const b=measuredTravelBasis({dx:3,dy:4,speed:5});
  assert.ok(b);
  assert.ok(Math.abs(b.forwardX-.6)<1e-12);
  assert.ok(Math.abs(b.forwardY-.8)<1e-12);
  assert.ok(Math.abs(b.forwardX*b.lateralX+b.forwardY*b.lateralY)<1e-12);
  assert.ok(Math.abs(Math.hypot(b.lateralX,b.lateralY)-1)<1e-12);
});
test('stationary, implausible or invalid movement creates no arrow',()=>{
  for(const input of [
    null,undefined,{dx:0,dy:0,speed:0},
    {dx:.0001,dy:0,speed:1},
    {dx:.1,dy:0,speed:.1},
    {dx:3,dy:4,speed:40},
    {dx:NaN,dy:2,speed:5},
    {dx:1,dy:Infinity,speed:3},
  ]) {
    assert.equal(measuredTravelBasis(input),null);
    assert.equal(travelChevron({x:40,y:25},input),null);
  }
});
test('no chevron outside field boundaries or from missing positions',()=>{
  assert.equal(travelChevron({x:119.5,y:25},{dx:.5,dy:0,speed:5}),null);
  assert.equal(travelChevron({x:60,y:53},{dx:0,dy:.5,speed:5}),null);
  assert.equal(travelChevron({x:NaN,y:25},{dx:.5,dy:0,speed:5}),null);
});
