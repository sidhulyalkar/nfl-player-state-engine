/** NFL tracking field coordinates -> WebGL world (yards), with true camera projection.
 * This file has no DOM/React/GL dependencies so geometry can be tested in Node.
 */
export type Vec3 = readonly [number, number, number];
export type CameraPreset = 'broadcast' | 'all22' | 'overhead';
export interface Orbit {
  azimuth: number;
  elevation: number;
  distance: number;
  target: Vec3;
  fovRadians: number;
}
export interface CameraBasis {
  eye: Vec3;
  forward: Vec3;
  right: Vec3;
  up: Vec3;
  aspect: number;
  fovRadians: number;
}
const PI = Math.PI;
export const FIELD_LENGTH = 120;
export const FIELD_WIDTH = 53.3;
export const clamp = (v: number, a: number, b: number): number => Math.max(a, Math.min(b, v));
export function fieldPoint(x: number, y: number, elevation = 0): Vec3 {
  if (![x, y, elevation].every(Number.isFinite) || x < 0 || x > FIELD_LENGTH || y < 0 || y > FIELD_WIDTH)
    throw new Error('Invalid or out-of-bounds recorded NFL tracking coordinate');
  return [x - 60, elevation, y - FIELD_WIDTH / 2];
}
const sub = (a: Vec3,b: Vec3): Vec3 => [a[0]-b[0],a[1]-b[1],a[2]-b[2]];
export const dot = (a: Vec3,b: Vec3): number => a[0]*b[0]+a[1]*b[1]+a[2]*b[2];
export const cross = (a: Vec3,b: Vec3): Vec3 => [
  a[1]*b[2]-a[2]*b[1],
  a[2]*b[0]-a[0]*b[2],
  a[0]*b[1]-a[1]*b[0],
];
export function norm(v: Vec3): Vec3 {
  const n = Math.hypot(v[0],v[1],v[2]);
  if (!Number.isFinite(n) || n < 1e-9) throw new Error('Degenerate camera basis');
  return [v[0]/n,v[1]/n,v[2]/n];
}
export function defaultOrbit(preset: CameraPreset, target: Vec3 = [0, 0, 0]): Orbit {
  const base = preset === 'overhead'
    ? { azimuth: -0.55, elevation: 1.48, distance: 148 }
    : preset === 'all22'
      ? { azimuth: -0.34, elevation: 0.73, distance: 147 }
      : { azimuth: -1.10, elevation: 0.54, distance: 135 };
  return { ...base, target, fovRadians: 53 * PI / 180 };
}
export function orbitCamera(input: Orbit, aspect: number): CameraBasis {
  if (!Number.isFinite(aspect) || aspect <= 0) throw new Error('Invalid camera aspect');
  const elev = clamp(input.elevation, 0.16, 1.53);
  const distance = clamp(input.distance, 40, 260);
  const cos = Math.cos(elev);
  const eye: Vec3 = [
    input.target[0] + distance * cos * Math.cos(input.azimuth),
    input.target[1] + distance * Math.sin(elev),
    input.target[2] + distance * cos * Math.sin(input.azimuth),
  ];
  const forward = norm(sub(input.target, eye));
  const right = norm(cross(forward, [0,1,0]));
  const up = norm(cross(right,forward));
  return { eye, forward, right, up, aspect, fovRadians: input.fovRadians };
}
export interface Projected { x: number; y: number; depth: number; visible: boolean; }
export function projectToScreen(p: Vec3, camera: CameraBasis, width: number, height: number): Projected {
  const relative = sub(p, camera.eye);
  const depth = dot(relative, camera.forward);
  if (depth <= 0.01 || width <= 0 || height <= 0) return { x:0,y:0,depth,visible:false };
  const zoom = 1 / Math.tan(camera.fovRadians / 2);
  const clipX = dot(relative,camera.right) * zoom / camera.aspect / depth;
  const clipY = dot(relative,camera.up) * zoom / depth;
  return {
    x: (clipX + 1) * width / 2,
    y: (1 - clipY) * height / 2,
    depth,
    visible: Math.abs(clipX) <= 1 && Math.abs(clipY) <= 1,
  };
}
/** Float uniforms for WebGL shader using positive camera-depth convention. */
export function lensUniforms(camera: CameraBasis): Float32Array {
  const n = 0.1, f = 650;
  const zoom = 1 / Math.tan(camera.fovRadians / 2);
  return new Float32Array([
    zoom / camera.aspect, zoom, (f+n)/(f-n), (-2*f*n)/(f-n),
  ]);
}
/** Center view on recorded players, not an invented line of scrimmage. */
export function trackingFocus(points: readonly {x:number;y:number}[]): Vec3 {
  if (!points.length) return [0,0,0];
  const xs=points.filter(p=>Number.isFinite(p.x)&&Number.isFinite(p.y));
  if (!xs.length) return [0,0,0];
  const sum = xs.reduce<[number,number]>((v,p)=>[v[0]+p.x,v[1]+p.y],[0,0]);
  return [clamp(sum[0]/xs.length - 60,-40,40),0,clamp(sum[1]/xs.length - FIELD_WIDTH/2,-15,15)];
}
export function trackingDistance(a:{x:number;y:number},b:{x:number;y:number}):number {
  return Math.hypot(a.x-b.x,a.y-b.y);
}

/** A snap alignment exists only if an explicit source event marks it. */
export function sourceSnapIndex(frames: readonly {events:readonly string[]}[]): number {
  return frames.findIndex(f=>f.events.some(e=>['ball_snap','snap','snap_direct'].includes(e.toLowerCase())));
}
interface TrackingObservation {
  nfl_id:string|null;
  x:number;
  y:number;
  side:string|null;
}
export interface RecordedTrackFrame {
  frame_id:number;
  players: readonly TrackingObservation[];
}
export interface ObservedSegment {
  id:string;
  from: readonly [number,number];
  to: readonly [number,number];
  side:'offense'|'defense'|null;
}
/** Exact recorded adjacent-frame positions only. No interpolation or extrapolation. */
export function observedTrailSegments(
  frames:readonly RecordedTrackFrame[],atIndex:number,lookback=30,
):ObservedSegment[]{
  const result:ObservedSegment[]=[];
  const end=Math.min(atIndex,frames.length-1);
  for(let k=Math.max(1,end-lookback);k<=end;k++){
    const before=frames[k-1],after=frames[k];
    if(!before||!after||after.frame_id!==before.frame_id+1)continue;
    const previous=new Map(before.players.filter(p=>p.nfl_id).map(p=>[p.nfl_id!,p]));
    for(const p of after.players){
      if(!p.nfl_id)continue;
      const src=previous.get(p.nfl_id);
      if(!src)continue;
      if(![src.x,src.y,p.x,p.y].every(Number.isFinite))continue;
      result.push({
        id:p.nfl_id,from:[src.x,src.y],to:[p.x,p.y],
        side:p.side==='offense'||p.side==='defense'?p.side:null,
      });
    }
  }
  return result;
}
