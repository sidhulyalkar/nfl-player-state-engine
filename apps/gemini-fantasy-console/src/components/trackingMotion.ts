/** Frame-local player motion from adjacent source positions, never imagined paths.
 * No assumption about NFL angular conventions for orientation or movement direction.
 */
export interface MotionSample { nfl_id: string | null; x: number; y: number }
export interface MotionFrame {
  frame_id: number;
  t_seconds_nominal: number;
  players: readonly MotionSample[];
}
export interface MotionVector {
  nfl_id: string;
  dx: number;
  dy: number;
  dt_seconds: number;
  computed_speed_yards_per_second: number;
  displacement_yards: number;
}
const FINITE = (v: number) => Number.isFinite(v);
const VALID = (p: MotionSample) => FINITE(p.x) && FINITE(p.y) &&
  p.x >= 0 && p.x <= 120 && p.y >= 0 && p.y <= 53.3;

/** Source adjacent frame only, so absent records never get bridged. */
export function motionAtFrame(frames: readonly MotionFrame[], index: number): MotionVector[] {
  if (!Number.isInteger(index) || index <= 0 || index >= frames.length) return [];
  const before = frames[index-1], after = frames[index];
  if (!before || !after || after.frame_id !== before.frame_id + 1) return [];
  const dt=after.t_seconds_nominal-before.t_seconds_nominal;
  // NFL tracking is nominally 10Hz. Refuse unusual timestamps instead of
  // drawing a misleading extrapolation.
  if (!FINITE(dt) || dt < .05 || dt > .15) return [];
  const old = new Map(before.players.filter(p => p.nfl_id && VALID(p))
    .map(p => [p.nfl_id!,p]));
  const seen = new Set<string>();
  const out: MotionVector[] = [];
  for (const p of after.players) {
    if (!p.nfl_id || !VALID(p) || seen.has(p.nfl_id)) continue;
    seen.add(p.nfl_id);
    const prior=old.get(p.nfl_id);
    if (!prior) continue;
    const dx=p.x-prior.x, dy=p.y-prior.y;
    const distance=Math.hypot(dx,dy);
    if (!FINITE(distance)) continue;
    out.push({
      nfl_id:p.nfl_id,dx,dy,
      dt_seconds:dt,
      displacement_yards:distance,
      computed_speed_yards_per_second:distance/dt,
    });
  }
  return out;
}

/** Sum strictly observed adjacent-frame distance; gaps mean lower bound only. */
export function observedDistance(frames: readonly MotionFrame[], playerId: string, through: number) {
  let yards=0, pairs=0;
  for (let i=1;i<=Math.min(through,frames.length-1);i++) {
    const sample=motionAtFrame(frames,i).find(p=>p.nfl_id===playerId);
    if (sample) {yards += sample.displacement_yards; pairs++;}
  }
  return { yards, observed_pairs:pairs, complete: pairs===Math.max(0,Math.min(through,frames.length-1)) };
}
