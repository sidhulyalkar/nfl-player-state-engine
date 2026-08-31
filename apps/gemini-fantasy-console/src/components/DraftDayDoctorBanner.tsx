import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, CheckCircle2, RefreshCw, ShieldAlert, Stethoscope } from 'lucide-react';
import '../draft-day-doctor.css';

type DoctorStatus = 'READY' | 'PROVISIONAL' | 'BLOCKED';

type DoctorCheck = {
  code: string;
  status: DoctorStatus;
  detail: string;
  remediation?: string | null;
};

type LeagueDoctor = {
  league_id: string;
  league_name: string;
  platform: string;
  status: DoctorStatus;
  can_use_core_draft_board: boolean;
  blocking_reasons: string[];
  provisional_reasons: string[];
};

type DoctorReport = {
  status: DoctorStatus;
  can_open_war_room: boolean;
  all_requested_leagues_usable: boolean;
  checks: DoctorCheck[];
  leagues: LeagueDoctor[];
  blocking_reasons: string[];
  provisional_reasons: string[];
  checked_at_utc: string;
};

function statusIcon(status: DoctorStatus) {
  if (status === 'READY') return <CheckCircle2 size={17}/>;
  if (status === 'BLOCKED') return <ShieldAlert size={17}/>;
  return <AlertTriangle size={17}/>;
}

export function DraftDayDoctorBanner() {
  const [report, setReport] = useState<DoctorReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let active = true;
    let controller: AbortController | null = null;

    async function refresh() {
      controller?.abort();
      controller = new AbortController();
      setLoading(true);
      try {
        const response = await fetch('/api/pse/v1/draft/doctor', { signal: controller.signal });
        if (!response.ok) throw new Error(`Draft-Day Doctor returned HTTP ${response.status}`);
        const payload = await response.json() as DoctorReport;
        if (!active) return;
        setReport(payload);
        setError(null);
      } catch (reason) {
        if (!active || controller.signal.aborted) return;
        setError(reason instanceof Error ? reason.message : 'Draft-Day Doctor unavailable');
      } finally {
        if (active && !controller.signal.aborted) setLoading(false);
      }
    }

    void refresh();
    const interval = window.setInterval(() => void refresh(), 60_000);
    return () => {
      active = false;
      controller?.abort();
      window.clearInterval(interval);
    };
  }, []);

  const finding = useMemo(() => {
    if (!report) return null;
    const global = report.checks.find((check) => check.status === 'BLOCKED')
      ?? report.checks.find((check) => check.status === 'PROVISIONAL');
    if (global) return global;
    for (const league of report.leagues) {
      if (league.status === 'BLOCKED') {
        return {
          code: league.blocking_reasons[0] ?? 'LEAGUE_BLOCKED',
          status: 'BLOCKED' as const,
          detail: `${league.league_name} is blocked for actual-draft use.`,
          remediation: 'Open the detailed doctor report or run scripts/draft_day_doctor.py for the exact remediation.',
        };
      }
    }
    for (const league of report.leagues) {
      if (league.status === 'PROVISIONAL') {
        return {
          code: league.provisional_reasons[0] ?? 'LEAGUE_PROVISIONAL',
          status: 'PROVISIONAL' as const,
          detail: `${league.league_name} is usable with an explicitly bounded caveat.`,
          remediation: 'Use the doctor endpoint or CLI to inspect the active caveat before close decisions.',
        };
      }
    }
    return null;
  }, [report]);

  if (!report && !error) {
    return <div className="doctor-banner loading"><RefreshCw size={16} className="spin"/><span>Checking draft-day authority…</span></div>;
  }

  if (error && !report) {
    return <div className="doctor-banner blocked"><ShieldAlert size={17}/><div><strong>Readiness diagnosis unavailable</strong><span>{error}</span></div></div>;
  }

  if (!report) return null;
  const usable = report.leagues.filter((league) => league.can_use_core_draft_board).length;
  return <div className={`doctor-banner ${report.status.toLowerCase()}`}>
    <div className="doctor-verdict">{statusIcon(report.status)}<div><span>DRAFT-DAY DOCTOR</span><strong>{report.status}</strong></div></div>
    <div className="doctor-summary"><Stethoscope size={16}/><span>{report.can_open_war_room ? 'Core War Room authority is usable.' : 'Do not rely on the War Room yet.'} {report.leagues.length ? `${usable}/${report.leagues.length} installed league${report.leagues.length === 1 ? '' : 's'} core-usable.` : 'No installed league is available.'}</span></div>
    <div className="doctor-finding"><strong>{finding?.code.replaceAll('_', ' ') ?? 'ALL CHECKS GREEN'}</strong><span>{finding?.detail ?? 'Champion, NFL state, league, and timing surfaces passed the active doctor checks.'}</span>{finding?.remediation && <small>{finding.remediation}</small>}</div>
    {loading && <RefreshCw size={14} className="spin doctor-refresh"/>}
  </div>;
}
