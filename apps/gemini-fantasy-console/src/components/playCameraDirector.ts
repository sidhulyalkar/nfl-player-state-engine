/** Camera director for source-observed spatial positions. Never guesses ball/targets/coverage. */
import {clamp, fieldPoint, type Vec3} from './football3dMath';

export interface CameraCue {
  target:Vec3;
  distance:number;
  label:string;
  evidence:'RECORDED_BALL'|'RECORDED_PLAYER'|'OBSERVED_GROUP';
}
export interface DirectorFrame {
  frame_id:number;
  events:readonly string[];
  ball:{x:number;y:number}|null;
  players:readonly {nfl_id:string|null;x:number;y:number}[];
}
const valid=(v:{x:number;y:number}|null|undefined):v is {x:number;y:number}=>
  !!v&&Number.isFinite(v.x)&&Number.isFinite(v.y)&&v.x>=0&&v.x<=120&&v.y>=0&&v.y<=53.3;
const tagged=(labels:readonly string[],parts:readonly string[])=>
  labels.some(e=>parts.some(part=>e.toLowerCase().includes(part)));
/** No camera update on unrecorded frame gaps; hold last observed pose. */
export function recordedCameraCue(frame:DirectorFrame,isGap:boolean,selectedId:string|null=null):CameraCue|null {
  if(isGap)return null;
  const labels=frame.events;
  const ball=valid(frame.ball)?frame.ball:null;
  const selected=frame.players.find(p=>p.nfl_id===selectedId&&valid(p));
  const players=frame.players.filter(valid);
  const point=ball??selected??(players.length?{
    x:players.reduce((sum,p)=>sum+p.x,0)/players.length,
    y:players.reduce((sum,p)=>sum+p.y,0)/players.length,
  }:null);
  if(!point)return null;
  const released=tagged(labels,['pass_forward','pass_arrived','pass_outcome','handoff']);
  const terminal=tagged(labels,['touchdown','tackle','out_of_bounds','sack','pass_outcome_caught']);
  const snap=tagged(labels,['ball_snap','snap_direct']);
  const distance=terminal?75:released?83:snap?100:96;
  return {
    target:fieldPoint(point.x,point.y),
    distance:clamp(distance,60,180),
    label:ball?'Follow recorded ball':selected?'Follow selected player':'Frame centroid of observed players',
    evidence:ball?'RECORDED_BALL':selected?'RECORDED_PLAYER':'OBSERVED_GROUP',
  };
}
/** A synthetic teaching demo is deliberately not passed through the recorded-data director. */
export function syntheticCameraCue(point:{x:number;y:number}|null,phase:'presnap'|'live'|'outcome'):CameraCue|null {
  if(!valid(point))return null;
  return {target:fieldPoint(point.x,point.y),distance:phase==='presnap'?108:phase==='live'?83:73,
    label:'Illustrative camera',evidence:'OBSERVED_GROUP'};
}
export function smoothOrbitTarget(
  current:Vec3,wanted:Vec3,dtSeconds:number,
):Vec3 {
  // Stable under variable refresh/frame rate; no overshoot and no jump across source gaps.
  const alpha=1-Math.exp(-3.8*clamp(dtSeconds,0,.1));
  return [
    current[0]+(wanted[0]-current[0])*alpha,
    current[1]+(wanted[1]-current[1])*alpha,
    current[2]+(wanted[2]-current[2])*alpha,
  ];
}
