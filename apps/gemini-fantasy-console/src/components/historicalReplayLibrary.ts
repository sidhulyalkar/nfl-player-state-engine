/** Local-only replay playlist. No persistence, network upload or inferred data. */
import type { HistoricalReplay } from './historicalReplaySchema';

export const MAX_REPLAY_LIBRARY = 12;
export const MAX_REPLAY_IMPORT_BYTES = 50_000_000;
export const MAX_REPLAY_FILE_BYTES = 25_000_000;

export function replayKey(replay: Pick<HistoricalReplay,'game_id'|'play_id'>): string {
  return JSON.stringify([replay.game_id,replay.play_id]);
}

export function replayLabel(replay: HistoricalReplay): string {
  return 'Game '+replay.game_id+' · play '+replay.play_id+
    ' · '+replay.frame_count+' recorded frames';
}

/** Atomic addition. Never allow two different datasets to claim one play slot. */
export function mergeReplayLibrary(
  existing: readonly HistoricalReplay[],
  additions: readonly HistoricalReplay[],
): HistoricalReplay[] {
  if (!additions.length) return [...existing];
  const next=[...existing];
  for(const replay of additions){
    const key=replayKey(replay);
    const previous=next.find(p=>replayKey(p)===key);
    if(previous){
      // A duplicate with different coordinates or rights claims must never
      // quietly replace a previously inspected source observation.
      if(JSON.stringify(previous)!==JSON.stringify(replay)){
        throw new Error('Conflicting data for game '+replay.game_id+' play '+replay.play_id+
          '. Remove the existing session or use a new isolated session.');
      }
      continue;
    }
    if(next.length>=MAX_REPLAY_LIBRARY)
      throw new Error('The research replay library holds at most '+MAX_REPLAY_LIBRARY+' plays per session.');
    next.push(replay);
  }
  return next;
}

export function selectReplay(
  library: readonly HistoricalReplay[],
  key: string,
): HistoricalReplay | null {
  return library.find(replay=>replayKey(replay)===key)??null;
}
