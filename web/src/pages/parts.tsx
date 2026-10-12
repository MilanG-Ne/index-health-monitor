import type { RunStatus, Severity } from "../api";

const STATUS_LABEL: Record<RunStatus, string> = {
  queued: "Queued",
  running: "Checking…",
  done: "Done",
  failed: "Failed",
};

export function StatusBadge({ status }: { status: RunStatus }) {
  return <span className={`badge badge-${status}`}>{STATUS_LABEL[status]}</span>;
}

const SEVERITY_LABEL: Record<Severity, string> = { error: "Error", warning: "Warning", info: "Notice" };

export function SeverityBadge({ severity }: { severity: Severity }) {
  return <span className={`badge sev-${severity}`}>{SEVERITY_LABEL[severity]}</span>;
}

export function Logo() {
  return (
    <span className="logo">
      <svg viewBox="0 0 32 32" aria-hidden="true">
        <rect width="32" height="32" rx="8" fill="#111a2e" />
        <path d="M8 17l5 5 11-12" stroke="#34d399" strokeWidth="3.5" fill="none" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      Index Health Monitor
    </span>
  );
}
