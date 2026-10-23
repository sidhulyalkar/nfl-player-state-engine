/** An observed NFL tracking sample is a point in time, not a continuous animation.
 * Explicit source-frame gaps must not silently become reconstructed movement.
 */
export interface TimelineFrame {
  frame_id: number;
  t_seconds_nominal: number;
}
export interface FrameTimeState {
  index: number;
  source_frame_id: number;
  is_gap: boolean;
  elapsed_since_observation: number;
}
/** Select most recent observed sample; flag intervening missing nominal frames. */
export function frameAtTime(
  frames: readonly TimelineFrame[],
  time: number,
  nominalHz = 10,
): FrameTimeState {
  if (!frames.length || !Number.isFinite(time) || !Number.isFinite(nominalHz) || nominalHz <= 0) {
    throw new Error('Invalid source frame timeline.');
  }
  let lo = 0, hi = frames.length - 1;
  while (lo < hi) {
    const mid = Math.ceil((lo + hi) / 2);
    if (frames[mid].t_seconds_nominal <= time) lo = mid;
    else hi = mid - 1;
  }
  const current = frames[lo];
  const elapsed = Math.max(0, time - current.t_seconds_nominal);
  // A sample can be held for its own nominal display interval (100 ms at
  // 10 Hz), but never as an unmarked replacement for a missing sample.
  const isGap = elapsed >= 1 / nominalHz - 1e-8
    && (lo === frames.length - 1 || frames[lo + 1].frame_id > current.frame_id + 1);
  return {
    index: lo, source_frame_id: current.frame_id,
    is_gap: isGap, elapsed_since_observation: elapsed,
  };
}
/** Move by actual recorded frame index, not an invented time offset. */
export function stepFrame(frames: readonly TimelineFrame[], index: number, delta: -1 | 1) {
  if (!frames.length || !Number.isInteger(index)) throw new Error('Invalid frame index.');
  const to = Math.max(0,Math.min(frames.length-1,index + delta));
  return {
    index: to, frame_id: frames[to].frame_id,
    time: frames[to].t_seconds_nominal,
    skipped_source_frames: Math.max(0,Math.abs(frames[to].frame_id-frames[Math.max(0,Math.min(index,frames.length-1))].frame_id)-1),
  };
}
export function displayClock(seconds: number) {
  if (!Number.isFinite(seconds)) return '—';
  return seconds.toFixed(2) + 's';
}
