import { AlertTriangle, CheckCircle2, Clock3, Database, GitBranch } from 'lucide-react';
import type { DataProvenance } from '../../shared/types';
import { ModeBadge } from './ModeBadge';

function displayDate(value?: string) {
  if (!value) return 'not reported';
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleString();
}

export function TrustStrip({ provenance }: { provenance: DataProvenance }) {
  const missing = provenance.missingInputs ?? [];
  return (
    <section className="trust-strip" aria-label="Data provenance">
      <ModeBadge mode={provenance.mode} />
      <span title="Model version"><GitBranch size={14}/>{provenance.modelVersion ?? 'model version unavailable'}</span>
      <span title="Prediction timestamp"><Clock3 size={14}/>{displayDate(provenance.predictionTimestamp)}</span>
      <span title="Local artifact file modification time">
        <Clock3 size={14}/>file modified {displayDate(provenance.artifactModifiedAt)}
      </span>
      <span title="Feature cutoff"><Database size={14}/>cutoff {displayDate(provenance.featureCutoff)}</span>
      {provenance.sourceCoverage !== undefined && (
        <span title="Resolved player identity coverage">
          <CheckCircle2 size={14}/>{(provenance.sourceCoverage * 100).toFixed(1)}% ID coverage
        </span>
      )}
      <span className={missing.length ? 'trust-warning' : ''}>
        {missing.length ? <AlertTriangle size={14}/> : <CheckCircle2 size={14}/>}
        {missing.length ? `${missing.length} missing input${missing.length === 1 ? '' : 's'}` : 'no missing inputs reported'}
      </span>
    </section>
  );
}
