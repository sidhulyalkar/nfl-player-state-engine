import type { DataMode } from '../../shared/types';

const labels: Record<DataMode, string> = {
  synthetic: 'SYNTHETIC DEMO',
  historical: 'HISTORICAL BACKTEST',
  live: 'LIVE',
  unverified: 'UNVERIFIED',
};

export function ModeBadge({ mode }: { mode: DataMode }) {
  return <span className={`mode-badge ${mode}`}>{labels[mode]}</span>;
}
