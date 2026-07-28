interface Props { floor?: number; median?: number; ceiling?: number; max?: number }

export function SparkRange({ floor = 0, median = 0, ceiling = 0, max = 35 }: Props) {
  const left = Math.max(0, Math.min(100, (floor / max) * 100));
  const middle = Math.max(0, Math.min(100, (median / max) * 100));
  const right = Math.max(0, Math.min(100, (ceiling / max) * 100));
  return (
    <div className="spark-range" aria-label={`Projection interval ${floor.toFixed(1)} to ${ceiling.toFixed(1)}`}>
      <div className="spark-track" />
      <div className="spark-band" style={{ left: `${left}%`, width: `${Math.max(2, right - left)}%` }} />
      <div className="spark-dot" style={{ left: `${middle}%` }} />
    </div>
  );
}
