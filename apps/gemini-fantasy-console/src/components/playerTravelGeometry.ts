/** Geometry for observation-derived TRAVEL markers, not player body orientation.
 *
 * BDB 2019 contains \`dir\` and newer tracking may contain \`o\`, but the
 * angular frame convention is not yet qualified across sources. Until it is,
 * visual heading must come ONLY from two validated adjacent x/y observations.
 */
export interface Displacement {
  dx: number;
  dy: number;
  speed: number;
}
export interface TravelBasis {
  forwardX: number;
  forwardY: number;
  lateralX: number;
  lateralY: number;
  speedYardsPerSecond: number;
}
const MIN_DISTANCE = 0.005;
const MIN_SPEED = 0.5;
const MAX_SPEED = 20;

/** Any invalid / stationary / physically implausible observation shows no heading. */
export function measuredTravelBasis(vector: Displacement | null | undefined): TravelBasis | null {
  if (!vector) return null;
  const { dx, dy, speed } = vector;
  const distance = Math.hypot(dx, dy);
  if (![dx,dy,speed,distance].every(Number.isFinite)
      || distance < MIN_DISTANCE || speed < MIN_SPEED || speed > MAX_SPEED) return null;
  const forwardX = dx / distance, forwardY = dy / distance;
  return {
    forwardX, forwardY,
    lateralX: -forwardY, lateralY: forwardX,
    speedYardsPerSecond: speed,
  };
}
export interface FieldXY { x: number; y: number; }
/** Move relative to a player's recorded location in actual field yards. */
export function travelPoint(
  center: FieldXY,
  basis: TravelBasis,
  lateralYards: number,
  forwardYards: number,
): FieldXY {
  return {
    x:center.x+basis.lateralX*lateralYards+basis.forwardX*forwardYards,
    y:center.y+basis.lateralY*lateralYards+basis.forwardY*forwardYards,
  };
}
/** Optional glyph is drawn only when ALL vertices remain on the field. */
export function travelChevron(center: FieldXY, vector: Displacement | null | undefined):
    readonly [FieldXY,FieldXY,FieldXY] | null {
  const basis = measuredTravelBasis(vector);
  if (!basis || ![center.x,center.y].every(Number.isFinite)) return null;
  const tip=travelPoint(center,basis,0,1.95);
  const left=travelPoint(center,basis,-.55,1.25);
  const right=travelPoint(center,basis,.55,1.25);
  if ([tip,left,right].some(p=>p.x<0||p.x>120||p.y<0||p.y>53.3))return null;
  return [tip,left,right];
}
